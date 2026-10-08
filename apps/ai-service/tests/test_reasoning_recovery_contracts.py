"""Recovery boundaries for read-only work, reserve evidence and composed education."""

import json

import pytest
from test_conditional_financial_dependencies import RecordingGateway, request
from test_financial_review_repair import ask
from test_post_retest_recovery import PreciseGateway

from app.core.config import Settings
from app.core.schemas import CoachRequest, TaskAssignment
from app.models.gateway import LocalFixtureModelGateway, ModelGeneration
from app.orchestrator import AgentOrchestrator
from app.tools.recurring_forecast import ledger_forecast


def calls(gateway, role):
    return [c for c in gateway.calls if c['system_prompt'].startswith('PROMPT_ID: ' + role + '\n')]


@pytest.mark.parametrize('language_safe', [False, None])
def test_original_draft_safety_does_not_prevent_owned_qualification_correction(language_safe):
    class Gateway(PreciseGateway):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            if kwargs['system_prompt'].startswith('PROMPT_ID: risk_compliance') and self.rounds == 1:
                verdict = json.loads(raw)
                verdict.pop('financial_language_safe')
                if language_safe is not None:
                    verdict['financial_language_safe'] = language_safe
                return json.dumps(verdict)
            return raw
    gateway = Gateway()
    response = ask(gateway)
    assert not response.blocked and gateway.rounds == 2
    assert response.answer == 'Recorded food is SGD 50. Coverage is incomplete.'
    first = next(e['details'] for e in response.audit['events'] if e['event_type'] == 'compliance.completed')
    assert first['answer_complete'] and first['repairable'] and not first['financial_language_safe']
    assert first['repair_blockers'] == []


@pytest.mark.parametrize('category', ['personal_advice', 'return_guarantee', 'privacy', 'injection'])
def test_unsafe_categories_still_deny_correction_and_explain_eligibility(category):
    class Gateway(PreciseGateway):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            if kwargs['system_prompt'].startswith('PROMPT_ID: risk_compliance'):
                verdict = json.loads(raw)
                verdict['block_categories'] = [category]
                verdict['financial_language_safe'] = False
                return json.dumps(verdict)
            return raw
    gateway = Gateway()
    response = ask(gateway)
    assert response.blocked and gateway.rounds == len(gateway.writes) == 1
    review = next(e['details'] for e in response.audit['events'] if e['event_type'] == 'compliance.completed')
    assert 'REVIEW_CATEGORY_NOT_CORRECTABLE' in review['repair_blockers']


class ReconciliationGateway(RecordingGateway):
    def __init__(self):
        super().__init__()
        self.plans = 0

    def generate(self, **kwargs):
        payload = json.loads(kwargs['user_prompt'])
        role = kwargs['system_prompt'].splitlines()[0]
        if role == 'PROMPT_ID: router':
            self.calls.append(kwargs)
            message = payload['message']
            return json.dumps({'selected_agents': ['spending', 'budget', 'goal_strategy'],
                'rationale': ['Recorded actual-versus-limit reconciliation informs goal feasibility.'],
                'budget_capture': True, 'budget_planning': True, 'budget_capacity_query': True,
                'task_assignments': [
                    {'agent': 'spending', 'question': message, 'source_quotes': [message], 'operation': 'analysis'},
                    {'agent': 'budget', 'question': message, 'source_quotes': [message],
                     'operation': 'reconciliation', 'requires_spending': True, 'requires_income': False},
                    {'agent': 'goal_strategy', 'question': 'Assess saved goal feasibility',
                     'source_quotes': [message], 'operation': 'analysis', 'goal_mode': 'standard', 'requires_capacity': True}]})
        if role == 'PROMPT_ID: dependency_planner' and payload['agent'] == 'budget':
            self.calls.append(kwargs)
            self.plans += 1
            if self.plans == 1:
                return json.dumps({'status': 'ready'})
            return json.dumps({'status': 'needs_dependency', 'requests': [
                {key: value for key, value in option.items() if key != 'selection_guidance'}
                for option in payload['allowed_requests']]})
        return super().generate(**kwargs)


@pytest.mark.parametrize('message', [
    'Compare logged categories with existing limits, then assess all goals against the reconciled plan.',
    'Use the expense breakdown to assess category pressures and explain whether the shared goal pool is sufficient.',
])
def test_read_only_reconciliation_preserves_dependency_planning_even_with_capture_flags(message):
    gateway = ReconciliationGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER='local_fixture'), gateway=gateway).handle(
        request(message, [], capacity=True))
    assert not response.blocked and gateway.plans == 2  # Contradictory ready decision gets one contract correction.
    assert {edge['capability'] for edge in response.audit['dependency_edges']} == {
        'transaction_category_totals', 'monthly_savings_capacity'}
    assert not calls(gateway, 'budget_capture')
    assert not response.audit['turn_decision']['budget_capture']
    assert not response.audit['turn_decision']['budget_planning']
    assert not any('budget_draft' in result.data for result in response.agent_results)


def test_reserve_classification_acquires_aggregates_when_router_omits_education_topic():
    class Gateway(RecordingGateway):
        def generate(self, **kwargs):
            role = kwargs['system_prompt'].splitlines()[0]
            if role == 'PROMPT_ID: router':
                self.calls.append(kwargs)
                message = json.loads(kwargs['user_prompt'])['message']
                return json.dumps({'selected_agents': ['goal_strategy'], 'rationale': ['Explain a reserve benchmark.'],
                    'task_assignments': [{'agent': 'goal_strategy', 'question': message, 'source_quotes': [message],
                                          'requires_capacity': False, 'requires_spending': True}]})
            if role == 'PROMPT_ID: goal_input_requirements':
                self.calls.append(kwargs)
                return json.dumps({'requires_capacity': False, 'goal_mode': 'emergency_reserve'})
            return super().generate(**kwargs)
    gateway = Gateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER='local_fixture'), gateway=gateway).handle(
        request('Explain how my logged expenses inform a rainy-day reserve benchmark.', []))
    assert not response.blocked and response.selected_agents == ['goal_strategy']
    goal = response.agent_results[0]
    assert goal.data['emergency_fund']['monthly_logged_spending'] == [{'month': '2026-10', 'currency': 'SGD', 'amount': 660}]
    assert goal.data['emergency_fund']['expense_coverage'] == 'unconfirmed'
    assert goal.data.get('calculation_scope') != 'saved_goal_arithmetic'
    assert any(e['event_type'] == 'dependency.requested' and e['details']['capability'] == 'education_context'
               for e in response.audit['events'])
    assert {edge['capability'] for edge in response.audit['dependency_edges']} == {'education_context'}


def recurring_row(**updates):
    return {'description': 'Lease', 'category': 'housing', 'amount': {'amount': 1800},
        'occurred_on': '2026-10-01', 'obligation_id': 'lease-1',
        'recurrence': {'frequency': 'monthly', 'first_on': '2026-10-01', 'next_due_on': '2026-11-01'}, **updates}


@pytest.mark.parametrize('legacy_capture', [True, False])
def test_forecast_grounding_is_read_only_and_review_can_correct_its_payment_qualification(legacy_capture):
    class Gateway(PreciseGateway):
        def __init__(self):
            super().__init__()
            self.calls = []
        def generate(self, **kwargs):
            self.calls.append(kwargs)
            role = kwargs['system_prompt'].splitlines()[0]
            if role == 'PROMPT_ID: router':
                message = json.loads(kwargs['user_prompt'])['message']
                return json.dumps({'selected_agents': ['spending'], 'rationale': ['Forecast explicit ledger terms.'],
                    'task_assignments': [{'agent': 'spending', 'question': message, 'source_quotes': [message],
                                          'operation': 'forecast'}],
                    'spending_capture': legacy_capture, 'spending_scope': {'kind': 'periods', 'periods': ['2026-11-01']}})
            if role == 'PROMPT_ID: spending_capture':
                return json.dumps({'action': 'forecast', 'query_start': '2026-11-01', 'query_end': '2026-11-30'})
            if role == 'PROMPT_ID: agent_spending':
                self.writes.append(json.loads(kwargs['user_prompt']))
                return json.dumps({'summary': 'The November projection is SGD 1800. ' + (
                    'It is paid.' if len(self.writes) == 1 else 'It is not proof of payment.'),
                    'rationale': ['Explicit scheduled obligation.'], 'confidence': .8})
            if role == 'PROMPT_ID: risk_compliance':
                self.rounds += 1
                if self.rounds == 1:
                    return json.dumps({'blocked': True, 'request_allowed': True, 'complete': True, 'missing_points': [],
                        'financial_language_safe': False, 'block_categories': ['factual_qualification'],
                        'blocking_issues': [{'section_id': 'spending', 'action': 'qualify', 'claim_quote': 'It is paid.',
                                            'requirement': 'Distinguish a projection from recorded payment.'}],
                        'policy_notes': ['A projection is not a payment.'], 'summary': 'Qualification required.',
                        'rationale': ['The calendar dates are conditional.'], 'confidence': 1})
                return LocalFixtureModelGateway.generate(self, **kwargs)
            return LocalFixtureModelGateway.generate(self, **kwargs)
    gateway = Gateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER='local_fixture'), gateway=gateway).handle(
        CoachRequest(user_id='u', session_id='s', message='Explain November scheduled bills and recorded payments.',
            snapshot={'period_start': '2026-11-01', 'recurring_expenses': [recurring_row()]}))
    assert not response.blocked and gateway.rounds == 2
    assert gateway.writes[0]['grounding'] == gateway.writes[1]['grounding']
    forecast = response.agent_results[0].data['recurring_forecast']
    assert forecast['total'] == 1800 and forecast['occurrences'][0]['due_on'] == '2026-11-01'
    assert response.agent_results[0].data['recorded_payments'] == {}
    assert 'not proof of payment' in response.answer
    assert not response.audit['turn_decision']['spending_capture']


@pytest.mark.parametrize('change_unaffected', [False, True])
def test_education_qualification_edits_preserve_unaffected_rendered_content(change_unaffected):
    class Gateway(RecordingGateway):
        def __init__(self):
            super().__init__()
            self.rounds, self.writes = 0, []

        def generate(self, **kwargs):
            role = kwargs['system_prompt'].splitlines()[0]
            payload = json.loads(kwargs['user_prompt'])
            if role == 'PROMPT_ID: agent_investment_education':
                self.calls.append(kwargs)
                self.writes.append(payload)
                source_id = payload['grounding']['sources'][0]['source_id']
                first = 'Holdings can be spread across assets.'
                if len(self.writes) > 1 and change_unaffected:
                    first = 'Holdings have changed.'
                claim = ('Diversification eliminates all risk.' if len(self.writes) == 1
                         else 'Diversification leaves market risk.')
                return json.dumps({'summary': first + ' [source:' + source_id + '] ' + claim,
                    'source_ids': [source_id], 'rationale': ['Explain diversification and its scope.'], 'confidence': .8})
            if role == 'PROMPT_ID: risk_compliance':
                self.calls.append(kwargs)
                self.rounds += 1
                if self.rounds == 1:
                    return json.dumps({'blocked': True, 'request_allowed': True, 'complete': True, 'missing_points': [],
                        'financial_language_safe': False, 'block_categories': ['factual_qualification'],
                        'blocking_issues': [{'section_id': 'investment_education', 'action': 'qualify',
                            'claim_quote': 'Diversification eliminates all risk.',
                            'requirement': 'Qualify diversification without rewriting the supported explanation.'}],
                        'summary': 'Qualification required.', 'policy_notes': ['Risk remains.'],
                        'rationale': ['The original claim is too broad.'], 'confidence': 1})
                return LocalFixtureModelGateway.generate(self, **kwargs)
            return super().generate(**kwargs)

    gateway = Gateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER='local_fixture'), gateway=gateway).handle(
        CoachRequest(user_id='u', session_id='s', message='Explain diversification.', requested_agents=['investment_education']))
    assert response.blocked is change_unaffected
    assert gateway.rounds == (1 if change_unaffected else 2)
    assert gateway.writes[1]['grounding'] == gateway.writes[0]['grounding']
    assert gateway.writes[1]['review_corrections'][0]['original_claim'] == 'Diversification eliminates all risk.'
    if not change_unaffected:
        assert gateway.writes[1]['original_summary'].startswith('Holdings can be spread across assets. [source:')
        assert response.answer.startswith('Holdings can be spread across assets. [')
        assert response.answer.endswith('Diversification leaves market risk.')


def test_forecast_identity_and_cadence_do_not_infer_schedules_or_double_count_payments():
    from app.core.schemas import Transaction
    rows = [recurring_row(), recurring_row(occurred_on='2026-10-15'),
            recurring_row(obligation_id=None), recurring_row(obligation_id='usd', amount={'currency': 'USD', 'amount': 300})]
    forecast = ledger_forecast([Transaction.model_validate(row) for row in rows],
        {'query_start': '2026-11-01', 'query_end': '2026-11-30'})
    assert forecast['total'] == 1800 and forecast['occurrence_count'] == 1
    assert forecast['unknown_schedule_count'] == 1 and forecast['excluded_currencies'] == ['USD']
    assert not forecast['records_complete']


def test_forecast_respects_the_extractor_amount_category_and_description_filters():
    from app.core.schemas import Transaction
    rows = [recurring_row(), recurring_row(obligation_id='lease-small', amount={'amount': 300}),
            recurring_row(obligation_id='rent-large', amount={'amount': 2200}),
            recurring_row(obligation_id='other-category', category='food'),
            recurring_row(obligation_id='other-description', description='Utilities')]
    forecast = ledger_forecast([Transaction.model_validate(row) for row in rows], {
        'query_start': '2026-11-01', 'query_end': '2026-11-30',
        'query_min_amount': 500, 'query_max_amount': 2000,
        'query_categories': ['HOUSING'], 'query_description': 'lease'})
    assert forecast['total'] == 1800 and forecast['occurrence_count'] == 1


class EducationCompositionGateway(RecordingGateway):
    def __init__(self, *, repeat=False, unknown_usage=False):
        super().__init__()
        self.rounds = 0
        self.repeat, self.unknown_usage = repeat, unknown_usage
    def generate(self, **kwargs):
        role = kwargs['system_prompt'].splitlines()[0]
        payload = json.loads(kwargs['user_prompt'])
        if role == 'PROMPT_ID: risk_compliance':
            self.calls.append(kwargs)
            self.rounds += 1
            if self.rounds == 1 or self.repeat:
                # This deliberately simulates a composition-owned defect, not a financial task.
                claim = payload['draft_answer'].splitlines()[-1]
                raw = json.dumps({'blocked': True, 'request_allowed': True, 'complete': True, 'missing_points': [],
                    'financial_language_safe': False, 'block_categories': ['factual_qualification'],
                    'blocking_issues': [{'section_id': 'draft', 'action': 'remove_claim', 'claim_quote': claim,
                                        'requirement': 'Remove the unsupported embellishment; preserve supported content.'}],
                    'summary': 'A composition claim needs removal.', 'policy_notes': ['Claim lacks support.'],
                    'rationale': ['Supported explanations can be preserved.'], 'confidence': 1})
            else:
                raw = LocalFixtureModelGateway.generate(self, **kwargs)
        elif role == 'PROMPT_ID: synthesizer':
            self.calls.append(kwargs)
            original = payload['original_draft']
            correction = payload['review_corrections'][0]
            raw = json.dumps({'answer': original[:correction['claim_start']] + original[correction['claim_end']:]})
        else:
            raw = super().generate(**kwargs)
        return raw if self.unknown_usage else ModelGeneration(raw, usage={
            'inputTokens': 1500, 'outputTokens': 500, 'totalTokens': 2000})


@pytest.mark.parametrize('repeat,unknown_usage', [(False, False), (True, False), (False, True)])
def test_education_only_composition_can_plan_its_first_synthesis_but_still_requires_review_and_usage(repeat, unknown_usage):
    gateway = EducationCompositionGateway(repeat=repeat, unknown_usage=unknown_usage)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER='openai'), gateway=gateway).handle(
        CoachRequest(user_id='u', session_id='s', message='Explain diversification.', requested_agents=['investment_education']))
    assert response.blocked is (repeat or unknown_usage)
    decision = next(e['details'] for e in response.audit['events'] if e['event_type'] == 'financial.review.repair_decision')
    if unknown_usage:
        assert 'REPAIR_USAGE_UNAVAILABLE' in decision['repair_blockers'] and gateway.rounds == 1
    else:
        assert decision['allowed'] and gateway.rounds == 2
        assert len(calls(gateway, 'synthesizer')) == 1
        estimates = [e['details'] for e in response.audit['events'] if e['event_type'] == 'financial.review.repair_estimate']
        assert any(e['component'] == 'synthesizer' and e['estimate_basis'] == 'planned_prompt_byte_bound' for e in estimates)
        synthesis = json.loads(calls(gateway, 'synthesizer')[0]['user_prompt'])
        assert synthesis['verified_grounding'][0]['data']['contexts']


@pytest.mark.parametrize('agent,operation,goal_mode', [('budget', 'forecast', None), ('spending', 'reconciliation', None),
                                                       ('investment_education', 'analysis', 'emergency_reserve')])
def test_task_operation_cannot_acquire_a_foreign_specialist_scope(agent, operation, goal_mode):
    with pytest.raises(ValueError):
        TaskAssignment(agent=agent, question='Explain this.', source_quotes=['Explain this.'],
                       operation=operation, goal_mode=goal_mode)

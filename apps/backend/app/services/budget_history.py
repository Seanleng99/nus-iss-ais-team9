"""Owned budget snapshots and repeat-spending evidence; restoration always previews."""
from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.services.financial_workspace import read_section, write_section


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    version_id: str = Field(min_length=1,max_length=64)


class AdaptiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    lookback_months: int = Field(default=3,ge=2,le=12)


def history(session,user_id,period):
    if period.day != 1:
        raise ValueError("Choose the first day of the month")
    return read_section(session,user_id,"history:"+str(period)) or []


def record_version(session,user_id,period,previous,current):
    entries=history(session,user_id,period)
    if entries and entries[-1]["snapshot"]==current:
        return
    now=datetime.now(UTC).isoformat()
    if not entries and previous:
        entries.append({"id":str(uuid4()),"saved_at":now,"reason":"Prior plan captured when history began","snapshot":previous})
    entries.append({"id":str(uuid4()),"saved_at":now,"reason":"Confirmed save","snapshot":current})
    write_section(session,user_id,"history:"+str(period),entries[-50:])


def restore_payload(session,user_id,request):
    from app.api.financial_schemas import BudgetUpsert
    from app.services.budget_constraints import constraint_questions
    version=next((v for v in history(session,user_id,request.period_start) if v["id"]==request.version_id),None)
    if not version:
        raise ValueError("Choose an available budget version belonging to this profile and month")
    snap=version["snapshot"]
    payload=BudgetUpsert(period_start=request.period_start,currency=snap["currency"],planning=snap["planning"],categories=[{"category":k,"limit_amount":v} for k,v in snap["categories"].items()])
    questions=constraint_questions(session,user_id,request.period_start,snap["categories"],payload.planning)
    if questions:
        raise ValueError("This version conflicts with current commitments: "+" ".join(questions))
    return payload


def adaptive_review(session,user_id,request,*,today=None):
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository
    from app.services.budget_capture import _snapshot
    from app.services.budget_constraints import cents
    from app.services.budget_continuity import add_months, fingerprint, local_today
    if request.period_start.day!=1:
        raise ValueError("Choose the first day of the planning month")
    today=today or local_today()
    anchor=min(request.period_start,today.replace(day=1))
    repo=SQLAlchemyBudgetRepository(session)
    current=repo.get(user_id,request.period_start)
    if not current or current.currency!="SGD":
        raise ValueError("Save an SGD budget for the month to review")
    observations={}
    periods=[]
    for offset in range(1,request.lookback_months+1):
        period=add_months(anchor,-offset)
        saved=repo.get(user_id,period)
        totals=repo.spending_by_category(user_id,period,currency="SGD")
        periods.append({"period":str(period),"limits":_snapshot(saved)["categories"] if saved and saved.currency=="SGD" else None,"recorded":totals})
        if not saved or saved.currency!="SGD":
            continue
        for c in saved.categories:
            if c.category in totals:
                observations.setdefault(c.category,[]).append({"period":str(period),"limit":float(c.limit_amount),"spent":totals[c.category]})
    suggestions=[]
    for c in current.categories:
        rows=observations.get(c.category,[])
        overruns=sum(cents(r["spent"])>cents(r["limit"]) for r in rows)
        if overruns>=2:
            average=(sum(cents(r["spent"]) for r in rows)+len(rows)-1)//len(rows)
            proposed=max(cents(c.limit_amount),average)
            if proposed>cents(c.limit_amount):
                suggestions.append({"category":c.category,"current_limit":float(c.limit_amount),"suggested_limit":proposed/100,"overrun_months":overruns,"observed_months":len(rows),"observations":rows})
    snapshot=_snapshot(current)
    return {"period_start":str(request.period_start),"read_only":True,"suggestions":suggestions,"baseline":snapshot,
        "evidence":fingerprint({"history":periods,"current":snapshot,"today":today}),"as_of":str(today),
        "warnings":["At least two completed months with recorded spending above their saved limits are required for a suggestion. The proposed limit is no lower than the current limit or observed monthly average, rounded up to cents.",
                    "Missing months/records are not treated as zero; coverage and one-off costs remain unverified. Review each suggestion and its funding gap before confirmation. No automatic changes or claims of predicted spending are made."]}


def describe_adaptive(result):
    lines=["Repeated-spending review — no changes saved.",f"Target month: {result['period_start']}; calculated {result['as_of']}."]
    for row in result["suggestions"]:
        lines.append(f"{row['category']}: exceeded its limit in {row['overrun_months']} of {row['observed_months']} observed months. Review a suggested limit of SGD {row['suggested_limit']:,.2f} (current SGD {row['current_limit']:,.2f}).")
    if not result["suggestions"]:
        lines.append("No repeated overrun meets the evidence threshold.")
    lines.extend(result["warnings"])
    return "\n\n".join(lines)

"""Custom CSS styles for Streamlit frontend."""

BUDGET_CSS = """
<style>
@media (max-width: 640px) {
    .st-key-budget-spending-summary [data-testid="stHorizontalBlock"],
    .st-key-budget-plan-summary [data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.5rem;
    }
    .st-key-budget-spending-summary [data-testid="stColumn"],
    .st-key-budget-plan-summary [data-testid="stColumn"] {
        width: 100% !important;
        min-width: 0 !important;
    }
    .st-key-budget-spending-summary [data-testid="stColumn"]:last-child {
        grid-column: 1 / -1;
    }
    .st-key-budget-spending-summary [data-testid="stMetricValue"],
    .st-key-budget-plan-summary [data-testid="stMetricValue"] {
        font-size: 1.25rem;
    }
}
</style>
"""

SPENDING_INSIGHTS_CSS = """
<style>
.spending-insights-header {
    display: flex;
    align-items: center;
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 16px;
    color: #1f2937;
}

.spending-insights-header .material-icons {
    margin-right: 8px;
    font-size: 20px;
}

.insight-card {
    transition: transform 0.2s, box-shadow 0.2s;
    cursor: pointer;
    height: 100%;
}

.insight-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.insight-card strong {
    font-size: 15px;
    line-height: 1.4;
}

.insight-card p {
    line-height: 1.5;
    margin: 0;
}

/* Material icons font */
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');
.material-icons {
    font-family: 'Material Icons';
    font-weight: normal;
    font-style: normal;
    font-size: 20px;
    display: inline-block;
    line-height: 1;
    text-transform: none;
    letter-spacing: normal;
    word-wrap: normal;
    white-space: nowrap;
    direction: ltr;
}
</style>
"""

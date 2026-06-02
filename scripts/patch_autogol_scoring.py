from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'backend_app.py'
s = p.read_text(encoding='utf-8')

s = s.replace('POINTS_SCORER = 3.5\n', 'POINTS_SCORER = 3.5\nPOINTS_OWN_GOAL = 2\n')

old = '''def scorer_or_own_goal_correct(row) -> bool:
    pred_og_1 = bool_value(row.get(PRED_OG_1))
    pred_og_2 = bool_value(row.get(PRED_OG_2))
    real_og_1 = bool_value(row.get(REAL_OG_1))
    real_og_2 = bool_value(row.get(REAL_OG_2))
    if pred_og_1 or pred_og_2:
        return (pred_og_1 and real_og_1) or (pred_og_2 and real_og_2)
    if real_og_1 or real_og_2:
        return False
    pred_scorer = normalize_scorer(row.get("pred_scorer"))
    real_scorers = normalize_scorers_list(row.get("real_scorers"))
    if pred_scorer == "" and real_scorers == "":
        return True
    if pred_scorer == "" or real_scorers == "":
        return False
    return pred_scorer.lower() in [clean_value(x).lower() for x in real_scorers.split(";") if clean_value(x) != ""]
'''

new = '''def scorer_correct(row) -> bool:
    pred_scorer = normalize_scorer(row.get("pred_scorer"))
    real_scorers = normalize_scorers_list(row.get("real_scorers"))
    if pred_scorer == "" and real_scorers == "":
        return True
    if pred_scorer == "" or real_scorers == "":
        return False
    return pred_scorer.lower() in [clean_value(x).lower() for x in real_scorers.split(";") if clean_value(x) != ""]


def own_goal_correct(row) -> bool:
    pred_og_1 = bool_value(row.get(PRED_OG_1))
    pred_og_2 = bool_value(row.get(PRED_OG_2))
    real_og_1 = bool_value(row.get(REAL_OG_1))
    real_og_2 = bool_value(row.get(REAL_OG_2))
    return (pred_og_1 and real_og_1) or (pred_og_2 and real_og_2)
'''
s = s.replace(old, new)

old = '''def score_row(row) -> pd.Series:
    exact = exact_score_correct(row)
    result = result_1x2_correct(row)
    scorer = scorer_or_own_goal_correct(row)
    exact_points = POINTS_EXACT_SCORE if exact else 0
    result_points = POINTS_1X2 if result else 0
    scorer_points = POINTS_SCORER if scorer else 0
    return pd.Series({"exact_score_points": exact_points, "result_1x2_points": result_points, "scorer_points": scorer_points, "total_points": exact_points + result_points + scorer_points})
'''

new = '''def score_row(row) -> pd.Series:
    exact = exact_score_correct(row)
    result = result_1x2_correct(row)
    scorer = scorer_correct(row)
    own_goal = own_goal_correct(row)
    exact_points = POINTS_EXACT_SCORE if exact else 0
    result_points = POINTS_1X2 if result else 0
    scorer_points = POINTS_SCORER if scorer else 0
    own_goal_points = POINTS_OWN_GOAL if own_goal else 0
    return pd.Series({"exact_score_points": exact_points, "result_1x2_points": result_points, "scorer_points": scorer_points, "own_goal_points": own_goal_points, "total_points": exact_points + result_points + scorer_points + own_goal_points})
'''
s = s.replace(old, new)
s = s.replace('"exact_score_points", "result_1x2_points", "scorer_points", "total_points",', '"exact_score_points", "result_1x2_points", "scorer_points", "own_goal_points", "total_points",')
s = s.replace('empty_standings_cols = ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "matches_scored"]', 'empty_standings_cols = ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "correct_own_goals", "matches_scored"]')
s = s.replace('correct_scorers=("scorer_points", lambda x: (x > 0).sum()),\n        matches_scored=("match_id", "count"),', 'correct_scorers=("scorer_points", lambda x: (x > 0).sum()),\n        correct_own_goals=("own_goal_points", lambda x: (x > 0).sum()),\n        matches_scored=("match_id", "count"),')
s = s.replace('standings = standings.sort_values(by=["total_points", "exact_scores", "correct_scorers", "correct_1x2"], ascending=[False, False, False, False]).reset_index(drop=True)', 'standings = standings.sort_values(by=["total_points", "exact_scores", "correct_scorers", "correct_own_goals", "correct_1x2"], ascending=[False, False, False, False, False]).reset_index(drop=True)')
s = s.replace('save_empty_csv_and_push(STANDINGS_PATH, ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "matches_scored"], f"Reset standings - {commit_suffix()}")', 'save_empty_csv_and_push(STANDINGS_PATH, ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "correct_own_goals", "matches_scored"], f"Reset standings - {commit_suffix()}")')

p.write_text(s, encoding='utf-8')
print('Patch autogol applicata a backend_app.py')

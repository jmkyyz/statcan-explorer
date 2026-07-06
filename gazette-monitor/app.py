"""Canada Gazette Regulatory Monitor — Flask app.

Routes:
  /                feed of matched items with filters + mark-as-seen
  /watchlist       rule manager (add / edit / delete / toggle)
  /run-ingest      manual ingest trigger with a run log
"""

import datetime as dt
import json

from flask import Flask, render_template, request, redirect, url_for

import ingest
from models import get_db, init_db

app = Flask(__name__)
init_db()

PORT = 5006


@app.template_filter("fromjson")
def fromjson_filter(s):
    try:
        return json.loads(s or "[]")
    except json.JSONDecodeError:
        return []


def _parse_date(s):
    try:
        return dt.date.fromisoformat(s) if s else None
    except ValueError:
        return None


@app.route("/")
def feed():
    conn = get_db()
    all_rules = conn.execute(
        "SELECT * FROM watchlist_rules ORDER BY label").fetchall()

    date_from = _parse_date(request.args.get("date_from", ""))
    date_to = _parse_date(request.args.get("date_to", ""))
    parts = request.args.getlist("part") or ["I", "II", "III"]
    rule_ids = [int(r) for r in request.args.getlist("rule") if r.isdigit()]
    hide_seen = request.args.get("hide_seen") == "1"

    sql = """
        SELECT m.id AS match_id, m.matched_on, m.seen,
               r.id AS rule_id, r.label AS rule_label,
               i.id AS item_id, i.section, i.department, i.act, i.title,
               i.item_url, i.comment_deadline, i.rias_summary,
               s.part, s.issue_date, s.volume, s.number
        FROM matches m
        JOIN gazette_items i ON i.id = m.item_id
        JOIN gazette_issues s ON s.id = i.issue_id
        JOIN watchlist_rules r ON r.id = m.rule_id
        WHERE 1=1
    """
    params = []
    if parts:
        sql += " AND s.part IN (%s)" % ",".join("?" * len(parts))
        params += parts
    if rule_ids:
        sql += " AND r.id IN (%s)" % ",".join("?" * len(rule_ids))
        params += rule_ids
    if date_from:
        sql += " AND s.issue_date >= ?"
        params.append(date_from.isoformat())
    if date_to:
        sql += " AND s.issue_date <= ?"
        params.append(date_to.isoformat())
    sql += " ORDER BY s.issue_date DESC, i.id DESC"

    rows = conn.execute(sql, params).fetchall()

    # Group match rows into one card per item
    today = dt.date.today()
    items, by_id = [], {}
    for row in rows:
        card = by_id.get(row["item_id"])
        if card is None:
            deadline = _parse_date(row["comment_deadline"])
            days_left = (deadline - today).days if deadline else None
            card = {
                "item_id": row["item_id"],
                "title": row["title"],
                "section": row["section"],
                "department": row["department"],
                "act": row["act"],
                "item_url": row["item_url"],
                "part": row["part"],
                "issue_date": row["issue_date"],
                "volume": row["volume"],
                "number": row["number"],
                "rias_summary": row["rias_summary"],
                "deadline": deadline,
                "days_left": days_left,
                "rules": [],
                "seen": True,
            }
            by_id[row["item_id"]] = card
            items.append(card)
        card["rules"].append({"label": row["rule_label"],
                              "matched_on": row["matched_on"]})
        if not row["seen"]:
            card["seen"] = False

    if hide_seen:
        items = [c for c in items if not c["seen"]]

    conn.close()
    return render_template(
        "feed.html", items=items, rules=all_rules,
        selected_parts=parts, selected_rules=rule_ids,
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        hide_seen=hide_seen)


@app.route("/item/<int:item_id>/toggle-seen", methods=["POST"])
def toggle_seen(item_id):
    conn = get_db()
    unseen = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE item_id = ? AND seen = 0",
        (item_id,)).fetchone()[0]
    conn.execute("UPDATE matches SET seen = ? WHERE item_id = ?",
                 (1 if unseen else 0, item_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("feed"))


# ---------------------------------------------------------------------------
# Watchlist manager
# ---------------------------------------------------------------------------

def _csv_to_json(raw):
    return json.dumps([s.strip() for s in (raw or "").split(",") if s.strip()])


@app.route("/watchlist")
def watchlist():
    conn = get_db()
    rules = conn.execute("SELECT * FROM watchlist_rules ORDER BY label").fetchall()
    edit_rule = None
    edit_id = request.args.get("edit", "")
    if edit_id.isdigit():
        edit_rule = conn.execute(
            "SELECT * FROM watchlist_rules WHERE id = ?", (int(edit_id),)).fetchone()
    conn.close()
    return render_template("watchlist.html", rules=rules, edit_rule=edit_rule)


@app.route("/watchlist/save", methods=["POST"])
def watchlist_save():
    label = request.form.get("label", "").strip()
    keywords = _csv_to_json(request.form.get("keywords", ""))
    departments = _csv_to_json(request.form.get("departments", ""))
    match_mode = request.form.get("match_mode", "any")
    if match_mode not in ("any", "all"):
        match_mode = "any"
    rule_id = request.form.get("rule_id", "")

    if label and json.loads(keywords):
        conn = get_db()
        if rule_id.isdigit():
            conn.execute(
                "UPDATE watchlist_rules SET label = ?, keywords = ?,"
                " departments = ?, match_mode = ? WHERE id = ?",
                (label, keywords, departments, match_mode, int(rule_id)))
        else:
            conn.execute(
                "INSERT INTO watchlist_rules (label, keywords, departments,"
                " match_mode, active) VALUES (?, ?, ?, ?, 1)",
                (label, keywords, departments, match_mode))
        conn.commit()
        conn.close()
    return redirect(url_for("watchlist"))


@app.route("/watchlist/<int:rule_id>/toggle", methods=["POST"])
def watchlist_toggle(rule_id):
    conn = get_db()
    conn.execute("UPDATE watchlist_rules SET active = 1 - active WHERE id = ?",
                 (rule_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("watchlist"))


@app.route("/watchlist/<int:rule_id>/delete", methods=["POST"])
def watchlist_delete(rule_id):
    conn = get_db()
    conn.execute("DELETE FROM matches WHERE rule_id = ?", (rule_id,))
    conn.execute("DELETE FROM watchlist_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("watchlist"))


# ---------------------------------------------------------------------------
# Manual ingest
# ---------------------------------------------------------------------------

@app.route("/run-ingest", methods=["GET", "POST"])
def run_ingest_view():
    log_lines = None
    if request.method == "POST":
        logger = ingest.IngestLogger(echo=False)
        try:
            ingest.run_ingest(logger=logger)
        except Exception as exc:
            logger.warn(f"Ingest aborted: {exc}")
        log_lines = logger.lines
    return render_template("ingest_log.html", log_lines=log_lines)


if __name__ == "__main__":
    app.run(debug=True, port=PORT)

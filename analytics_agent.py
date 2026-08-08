import pandas as pd


def calculate_trend(values):
    """
    Given a list of numbers in chronological order, returns a simple
    trend label by comparing the most recent value to the earlier average.

    This is intentionally simple (not machine learning) — a small,
    explainable rule that's easy to justify and defend in a viva.
    """
    if len(values) < 2:
        return "Not enough data"

    earlier_avg = sum(values[:-1]) / len(values[:-1])
    latest = values[-1]
    change = latest - earlier_avg

    if change <= -10:
        return "Declining"
    elif change >= 10:
        return "Improving"
    else:
        return "Stable"


def analyze_performance(csv_path, attendance_threshold=70, marks_threshold=50):
    """
    Reads assessment history data (multiple rows per student) and
    produces a trend-aware analysis instead of a single-point flag.
    """
    df = pd.read_csv(csv_path)

    results = []

    # Group all rows belonging to the same student together
    for student_name, student_data in df.groupby("student_name"):
        # Sort by assessment number so trend calculation reads in order
        student_data = student_data.sort_values("assessment_number")

        marks_history = student_data["marks"].tolist()
        attendance_history = student_data["attendance_percent"].tolist()

        latest_marks = marks_history[-1]
        latest_attendance = attendance_history[-1]

        marks_trend = calculate_trend(marks_history)
        attendance_trend = calculate_trend(attendance_history)

        # Build human-readable reasons instead of just a yes/no flag
        reasons = []
        if latest_marks < marks_threshold:
            reasons.append(f"Latest marks ({latest_marks}) below threshold")
        if latest_attendance < attendance_threshold:
            reasons.append(f"Latest attendance ({latest_attendance}%) below threshold")
        if marks_trend == "Declining":
            reasons.append("Marks trend is declining over recent assessments")
        if attendance_trend == "Declining":
            reasons.append("Attendance trend is declining")

        # A student needs support if there's at least one real reason —
        # not just a single low number, but low/declining evidence
        needs_support = len(reasons) > 0

        results.append({
            "student_name": student_name,
            "latest_marks": latest_marks,
            "marks_trend": marks_trend,
            "latest_attendance": latest_attendance,
            "attendance_trend": attendance_trend,
            "needs_support": needs_support,
            "reasons": "; ".join(reasons) if reasons else "No concerns"
        })

    result_df = pd.DataFrame(results)

    summary = {
        "total_students": len(result_df),
        "students_needing_support": result_df[result_df["needs_support"]]["student_name"].tolist()
    }

    return result_df, summary


if __name__ == "__main__":
    df, summary = analyze_performance("sample_trend_data.csv")

    print("📊 Academic Support Risk Report\n")
    for _, row in df.iterrows():
        status = "⚠️ NEEDS SUPPORT" if row["needs_support"] else "✅ OK"
        print(f"{status} — {row['student_name']}")
        print(f"   Marks: {row['latest_marks']} ({row['marks_trend']})")
        print(f"   Attendance: {row['latest_attendance']}% ({row['attendance_trend']})")
        print(f"   Reason: {row['reasons']}\n")
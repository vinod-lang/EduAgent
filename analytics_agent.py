import pandas as pd


def analyze_performance(csv_path, attendance_threshold=70, marks_threshold=50):
    """
    Reads a marks/attendance CSV and flags students who may need support.

    attendance_threshold: below this % attendance = flagged
    marks_threshold: below this average marks = flagged
    """
    df = pd.read_csv(csv_path)

    # Find all columns that contain test marks (so this works for any
    # number of tests, not just a fixed 3)
    marks_columns = [col for col in df.columns if "marks" in col.lower()]

    # Calculate each student's average mark across all tests
    df["average_marks"] = df[marks_columns].mean(axis=1)

    # A student is "at risk" if EITHER their attendance OR their average
    # marks fall below the threshold
    df["low_attendance"] = df["attendance_percent"] < attendance_threshold
    df["low_marks"] = df["average_marks"] < marks_threshold
    df["needs_support"] = df["low_attendance"] | df["low_marks"]

    # Build a simple summary
    summary = {
        "total_students": len(df),
        "class_average_marks": round(df["average_marks"].mean(), 2),
        "class_average_attendance": round(df["attendance_percent"].mean(), 2),
        "students_needing_support": df[df["needs_support"]]["student_name"].tolist()
    }

    return df, summary


if __name__ == "__main__":
    df, summary = analyze_performance("sample_marks.csv")

    print("📊 Class Summary")
    print(f"Total students: {summary['total_students']}")
    print(f"Class average marks: {summary['class_average_marks']}")
    print(f"Class average attendance: {summary['class_average_attendance']}%")

    print("\n⚠️ Students who may need support:")
    for name in summary["students_needing_support"]:
        print(f" - {name}")

    print("\nFull data:")
    print(df[["student_name", "average_marks", "attendance_percent", "needs_support"]])
from flask import Flask, render_template, request, send_file
from flask_compress import Compress
import pandas as pd
import json
import os

app = Flask(__name__)

# Enable gzip compression — reduces HTML/CSS/JS response size by 70-80%
Compress(app)
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/xml',
    'application/json', 'application/javascript'
]
app.config['COMPRESS_MIN_SIZE'] = 500  # Only compress responses > 500 bytes

# Cache static files for 1 hour
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.after_request
def add_cache_headers(response):
    """Add cache headers for better repeat-visit performance."""
    if 'text/html' in response.content_type:
        # Don't cache HTML (dynamic content)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    else:
        # Cache static assets for 1 hour
        response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

def process_file(path):

    df = pd.read_excel(path, header=None)

    df.columns = [
        "HTNO","SUBCODE","SUBJECT","INTERNAL",
        "EXTERNAL","TOTAL","GRADE","GP","CR"
    ]

    df = df[df["HTNO"].astype(str).str.contains("Q")]

    df["TOTAL"] = pd.to_numeric(df["TOTAL"], errors="coerce")
    df["GP"] = pd.to_numeric(df["GP"], errors="coerce")
    df["CR"] = pd.to_numeric(df["CR"], errors="coerce")

    # ALL CREDIT SUBJECTS (theory + lab)
    credit_subjects = df[df["CR"] > 0]

    # TOTAL MARKS
    total_marks = credit_subjects.groupby("HTNO")["TOTAL"].sum().reset_index()
    total_marks.columns = ["HTNO","Total Marks"]

    # SGPA
    sgpa = credit_subjects.groupby("HTNO").apply(
        lambda x: (x["GP"] * x["CR"]).sum() / x["CR"].sum()
    ).round(2).reset_index()
    sgpa.columns = ["HTNO","SGPA"]

    # THEORY SUBJECT PERCENTAGE (CR >= 3)
    theory = df[df["CR"] >= 3].copy()
    theory["Subject %"] = theory["TOTAL"]

    subject_percent = theory.pivot(
        index="HTNO",
        columns="SUBJECT",
        values="Subject %"
    ).round(2).reset_index()

    # OVERALL % based on theory subjects only
    subject_count = theory.groupby("HTNO").size().reset_index(name="Count")

    overall = total_marks.merge(subject_count,on="HTNO")

    overall["Overall %"] = (
        overall["Total Marks"] / (overall["Count"] * 100)
    ) * 100

    overall = overall[["HTNO","Overall %"]].round(2)

    # MAIN RESULT
    result = subject_percent.merge(total_marks,on="HTNO")
    result = result.merge(overall,on="HTNO")
    result = result.merge(sgpa,on="HTNO")

    result.insert(0,"S.No",range(1,len(result)+1))

    # RANK TABLES
    rank_df = total_marks.merge(sgpa,on="HTNO")

    rank_marks = rank_df.sort_values(
        by="Total Marks",ascending=False
    ).reset_index(drop=True)

    rank_marks.insert(0,"Rank",rank_marks.index+1)

    rank_sgpa = rank_df.sort_values(
        by="SGPA",ascending=False
    ).reset_index(drop=True)

    rank_sgpa.insert(0,"Rank",rank_sgpa.index+1)

    # FAILED STUDENTS
    failed = df[df["GRADE"].isin(["F","Ab"])]

    failed_group = failed.groupby("HTNO")["SUBJECT"].apply(
        lambda x:", ".join(x)
    ).reset_index()

    failed_group.columns=["HTNO","Failed Subjects"]

    failed_group.insert(0,"S.No",range(1,len(failed_group)+1))

    # SUBJECT PASS %
    total_students = df["HTNO"].nunique()

    pass_counts = credit_subjects.groupby("SUBJECT")["HTNO"].nunique().reset_index()

    subject_pass = pass_counts.copy()

    subject_pass.columns=["Subject","Passed Students"]

    subject_pass["Total Students"]=total_students

    subject_pass["Pass %"]=(
        subject_pass["Passed Students"]/total_students*100
    ).round(2)

    return result,failed_group,rank_marks,rank_sgpa,subject_pass


@app.route("/",methods=["GET","POST"])
def index():

    tables={}
    chart_data=None

    if request.method=="POST":

        file=request.files["file"]

        path=os.path.join(UPLOAD_FOLDER,file.filename)

        file.save(path)

        result,failed,rank_marks,rank_sgpa,subject_pass=process_file(path)

        tables["result"]=result.to_html(classes="table table-bordered",index=False)
        tables["failed"]=failed.to_html(classes="table table-bordered",index=False)
        tables["rank_marks"]=rank_marks.to_html(classes="table table-bordered",index=False)
        tables["rank_sgpa"]=rank_sgpa.to_html(classes="table table-bordered",index=False)
        tables["subject_pass"]=subject_pass.to_html(classes="table table-bordered",index=False)

        result.to_excel("uploads/output.xlsx",index=False)

        # Build chart data for frontend
        subjects_chart = []
        for _, row in subject_pass.iterrows():
            passed = int(row["Passed Students"])
            total = int(row["Total Students"])
            failed_count = total - passed
            subjects_chart.append({
                "name": row["Subject"],
                "passed": passed,
                "failed": failed_count,
                "pass_pct": float(row["Pass %"])
            })

        total_students = int(subject_pass["Total Students"].iloc[0]) if len(subject_pass) > 0 else 0
        overall_failed = len(failed)
        overall_passed = total_students - overall_failed

        chart_data = {
            "subjects": subjects_chart,
            "overall": {"passed": overall_passed, "failed": overall_failed}
        }

    return render_template("index.html", tables=tables, chart_data=json.dumps(chart_data) if chart_data else "null")


@app.route("/download")
def download():
    return send_file("uploads/output.xlsx",as_attachment=True)


if __name__=="__main__":
    app.run(debug=True)


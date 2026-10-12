from flask import Flask, render_template, request, send_file, session
from flask_compress import Compress
import pandas as pd
import json
import os
import uuid
import re
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Enable gzip compression — reduces HTML/CSS/JS response size by 70-80%
Compress(app)
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/xml',
    'application/json', 'application/javascript'
]
app.config['COMPRESS_MIN_SIZE'] = 500  # Only compress responses > 500 bytes
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit

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


# ═══════════════════════════════════════════════════════════════
# DYNAMIC EXCEL INGESTION SYSTEM
# ═══════════════════════════════════════════════════════════════

# Canonical column schema
CANONICAL_COLS = {
    "HTNO": ["htno", "hallticket", "hall_ticket", "hallticketno", "hall_ticket_no",
             "ht_no", "roll", "rollno", "roll_no", "rollnumber", "roll_number",
             "student_id", "studentid", "htno.", "ht no", "hall ticket no"],
    "SUBCODE": ["subcode", "subject_code", "subjectcode", "sub_code", "coursecode",
                "course_code", "code", "sub code", "subject code"],
    "SUBJECT": ["subject", "subject_name", "subjectname", "sub_name", "subname",
                "coursename", "course_name", "course", "subject name"],
    "INTERNAL": ["internal", "internalmarks", "internal_marks", "int_marks", "intmarks",
                 "int", "cie", "ia", "internal marks", "sessional"],
    "EXTERNAL": ["external", "externalmarks", "external_marks", "ext_marks", "extmarks",
                 "ext", "see", "external marks", "university"],
    "TOTAL": ["total", "totalmarks", "total_marks", "marks", "tot",
              "total marks", "obtained"],
    "GRADE": ["grade", "gradevalue", "grade_value", "lettergrade", "letter_grade",
              "result", "grade obtained"],
    "GP": ["gp", "gradepoints", "grade_points", "gradepoint", "grade_point",
           "gpts", "grade points", "gp obtained"],
    "CR": ["cr", "credits", "credit", "crs", "credit_hours", "credithours",
           "credit hours", "no of credits"]
}

# PT assessment column patterns
PT_PATTERNS = {
    "PT1": ["pt1", "pt-1", "pt 1", "periodic1", "periodic_1", "mid1", "mid-1", "mid 1"],
    "PT2": ["pt2", "pt-2", "pt 2", "periodic2", "periodic_2", "mid2", "mid-2", "mid 2"],
    "PT3": ["pt3", "pt-3", "pt 3", "periodic3", "periodic_3", "mid3", "mid-3", "mid 3"],
}


def normalize_col_name(name):
    """Normalize a column name for matching: lowercase, strip, remove extra whitespace/underscores."""
    if not isinstance(name, str):
        return str(name).strip().lower()
    return re.sub(r'[\s_]+', '', name.strip().lower())


def detect_header_row(df, max_scan=20):
    """
    Scan the first max_scan rows to find the header row.
    Returns the row index containing header-like values, or None.
    """
    # Collect all known canonical names for matching
    all_known = set()
    for canon, variants in CANONICAL_COLS.items():
        all_known.add(normalize_col_name(canon))
        for v in variants:
            all_known.add(normalize_col_name(v))

    best_row = None
    best_score = 0

    for i in range(min(max_scan, len(df))):
        row_vals = df.iloc[i].astype(str).tolist()
        score = 0
        for val in row_vals:
            normalized = normalize_col_name(val)
            if normalized in all_known:
                score += 1
        # Need at least 3 recognized column names (HTNO + some data cols)
        if score > best_score and score >= 3:
            best_score = score
            best_row = i

    return best_row


def map_columns(df_columns):
    """
    Map actual DataFrame columns to canonical names.
    Returns: (mapping_dict, unmapped_cols, pt_columns)
    mapping_dict: {canonical_name: actual_col_name}
    unmapped_cols: list of columns that couldn't be mapped
    pt_columns: {PT1/PT2/PT3: actual_col_name}
    """
    mapping = {}
    unmapped = []
    pt_cols = {}

    for col in df_columns:
        normalized = normalize_col_name(col)
        matched = False

        # Check canonical columns
        for canon, variants in CANONICAL_COLS.items():
            canon_norm = normalize_col_name(canon)
            variant_norms = [normalize_col_name(v) for v in variants]
            if normalized == canon_norm or normalized in variant_norms:
                mapping[canon] = col
                matched = True
                break

        # Check PT patterns
        if not matched:
            for pt_name, patterns in PT_PATTERNS.items():
                pt_norms = [normalize_col_name(p) for p in patterns]
                if normalized in pt_norms:
                    pt_cols[pt_name] = col
                    matched = True
                    break

        if not matched:
            unmapped.append(col)

    return mapping, unmapped, pt_cols


def extract_exam_metadata(df, header_row_idx):
    """
    Extract examination metadata from introductory rows above the header.
    Returns a dict with available metadata.
    """
    metadata = {
        "filename": "",
        "exam_info": "",
        "recount_info": ""
    }

    if header_row_idx is None or header_row_idx == 0:
        return metadata

    for i in range(header_row_idx):
        row_text = str(df.iloc[i, 0]) if pd.notna(df.iloc[i, 0]) else ""
        if "recounting" in row_text.lower() or "revaluation" in row_text.lower():
            metadata["recount_info"] = row_text.strip()
        elif "url" in row_text.lower() or "registration" in row_text.lower():
            metadata["exam_info"] = row_text.strip()
        elif row_text.strip() and metadata["exam_info"] == "":
            metadata["exam_info"] = row_text.strip()

    return metadata


def validate_schema(col_mapping, pt_cols):
    """
    Validate which calculations the workbook supports.
    Returns (supported_features dict, errors list)
    """
    features = {
        "basic_results": False,
        "marks_ranking": False,
        "sgpa_ranking": False,
        "subject_pass_fail": False,
        "failed_students": False,
        "pt_analysis": False
    }
    errors = []

    # Must have student ID and subject ID
    if "HTNO" not in col_mapping:
        errors.append("No student identifier column (HTNO/Roll No) detected.")
        return features, errors

    if "SUBJECT" not in col_mapping and "SUBCODE" not in col_mapping:
        errors.append("No subject identifier column detected.")
        return features, errors

    features["basic_results"] = True

    if "TOTAL" in col_mapping:
        features["marks_ranking"] = True

    if "GP" in col_mapping and "CR" in col_mapping:
        features["sgpa_ranking"] = True

    if "GRADE" in col_mapping:
        features["subject_pass_fail"] = True
        features["failed_students"] = True

    if len(pt_cols) > 0:
        features["pt_analysis"] = True

    return features, errors


def detect_htno_pattern(series):
    """
    Dynamically detect the hall-ticket number pattern from the data.
    Returns a regex pattern string that matches valid HTNOs.
    """
    # JNTUH HTNOs typically: 2 digits (year) + college code + branch digits
    # e.g., 23Q61A6601, 22Q65A6603
    # More generally: alphanumeric, 10+ chars, starting with digits
    sample = series.dropna().astype(str).head(50)
    # Filter for strings that look like HTNOs (alphanumeric, >= 8 chars)
    valid = sample[sample.str.match(r'^[A-Za-z0-9]{8,}$')]
    if len(valid) == 0:
        # Fallback: anything non-empty and not a header
        return None
    return True  # Signal that valid HTNOs exist


def process_file_dynamic(path, sheet_name=0):
    """
    Enhanced dynamic file processor.
    Returns: (results_dict, chart_data_dict, kpi_dict, metadata_dict, features_dict, error_msg)
    """
    try:
        # Read raw Excel without headers
        try:
            df_raw = pd.read_excel(path, header=None, sheet_name=sheet_name)
        except Exception as e:
            return None, None, None, None, None, f"Cannot read Excel file: {str(e)}"

        if df_raw.empty or len(df_raw) < 2:
            return None, None, None, None, None, "File is empty or has insufficient data."

        # Detect header row
        header_idx = detect_header_row(df_raw)

        if header_idx is None:
            # Try assuming first row is header
            header_idx = 0

        # Extract metadata from rows above header
        metadata = extract_exam_metadata(df_raw, header_idx)

        # Try to extract clean exam name if not already extracted
        if not metadata.get("exam_title"):
            raw_name = os.path.splitext(os.path.basename(path))[0]
            clean_name = re.sub(r'^[a-f0-9\-]{36}_', '', raw_name)
            clean_name = clean_name.replace('_', ' ').strip()
            if clean_name and clean_name.lower() not in ["test", "output", "upload"]:
                metadata["exam_title"] = clean_name
            else:
                metadata["exam_title"] = ""

        # Re-read with detected header
        df = df_raw.iloc[header_idx:].copy()
        df.columns = df.iloc[0]
        df = df.iloc[1:].reset_index(drop=True)

        # Drop completely empty rows
        df = df.dropna(how='all')

        # Map columns
        col_mapping, unmapped, pt_cols = map_columns(df.columns)

        # Validate schema
        features, validation_errors = validate_schema(col_mapping, pt_cols)

        if validation_errors:
            return None, None, None, metadata, features, "; ".join(validation_errors)

        # Rename columns to canonical names
        reverse_map = {v: k for k, v in col_mapping.items()}
        df = df.rename(columns=reverse_map)

        # Filter valid student rows (HTNOs)
        if "HTNO" in df.columns:
            df["HTNO"] = df["HTNO"].astype(str).str.strip()
            # Remove rows that are header repeats or empty
            df = df[~df["HTNO"].isin(["nan", "", "None", "HTNO"])]
            # Filter for alphanumeric HTNOs (at least 8 characters)
            df = df[df["HTNO"].str.match(r'^[A-Za-z0-9]{8,}$', na=False)]

        if len(df) == 0:
            return None, None, None, metadata, features, "No valid student records found after filtering."

        # Safe numeric conversions (never replace NaN with 0 silently)
        for col in ["TOTAL", "GP", "CR", "INTERNAL", "EXTERNAL"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Preserve subject identifiers
        if "SUBJECT" not in df.columns and "SUBCODE" in df.columns:
            df["SUBJECT"] = df["SUBCODE"]
        if "SUBCODE" not in df.columns and "SUBJECT" in df.columns:
            df["SUBCODE"] = df["SUBJECT"]

        # ── Now run the calculations ──

        # ALL CREDIT SUBJECTS (theory + lab)
        has_credits = "CR" in df.columns
        if has_credits:
            credit_subjects = df[df["CR"] > 0].copy()
        else:
            credit_subjects = df.copy()

        # ── TOTAL MARKS ──
        has_totals = "TOTAL" in df.columns
        total_marks = None
        if has_totals:
            total_marks = credit_subjects.groupby("HTNO")["TOTAL"].sum().reset_index()
            total_marks.columns = ["HTNO", "Total Marks"]

        # ── SGPA ──
        sgpa = None
        if features["sgpa_ranking"] and has_credits:
            # Filter out rows with NaN GP or CR for SGPA calc
            sgpa_data = credit_subjects.dropna(subset=["GP", "CR"])
            sgpa_data = sgpa_data[sgpa_data["CR"] > 0]
            if len(sgpa_data) > 0:
                sgpa = sgpa_data.groupby("HTNO").apply(
                    lambda x: (x["GP"] * x["CR"]).sum() / x["CR"].sum()
                    if x["CR"].sum() > 0 else 0
                ).round(2).reset_index()
                sgpa.columns = ["HTNO", "SGPA"]

        # ── Identify theory vs lab subjects ──
        if has_credits:
            subject_cr = credit_subjects.drop_duplicates("SUBJECT")[["SUBJECT", "CR"]].copy()
            theory_names = sorted(subject_cr[subject_cr["CR"] >= 3]["SUBJECT"].tolist())
            lab_names = sorted(subject_cr[subject_cr["CR"] < 3]["SUBJECT"].tolist())
        else:
            all_subjects = sorted(df["SUBJECT"].unique().tolist())
            theory_names = all_subjects
            lab_names = []

        # ── ALL SUBJECT MARKS pivot ──
        if has_totals:
            all_subs = credit_subjects.copy()
            all_subs["Subject %"] = all_subs["TOTAL"]

            subject_percent = all_subs.pivot_table(
                index="HTNO",
                columns="SUBJECT",
                values="Subject %",
                aggfunc='first'
            ).round(2).reset_index()

            # ── OVERALL % based on ALL credit subjects ──
            all_subject_count = credit_subjects.groupby("HTNO").size().reset_index(name="Count")

            overall = total_marks.merge(all_subject_count, on="HTNO")
            overall["Overall %"] = (
                overall["Total Marks"] / (overall["Count"] * 100)
            ) * 100
            overall = overall[["HTNO", "Overall %"]].round(2)

            # ── MAIN RESULT TABLE ──
            result = subject_percent.merge(total_marks, on="HTNO")
            result = result.merge(overall, on="HTNO")

            if sgpa is not None:
                result = result.merge(sgpa, on="HTNO")

            result.insert(0, "S.No", range(1, len(result) + 1))

            # Build ordered columns
            summary_cols = ["Total Marks", "Overall %"]
            if sgpa is not None:
                summary_cols.append("SGPA")
            ordered_cols = ["S.No", "HTNO"] + theory_names + lab_names + summary_cols
            # Only include columns that exist
            ordered_cols = [c for c in ordered_cols if c in result.columns]
            result = result[ordered_cols]

            # Store column grouping info
            result._theory_names = theory_names
            result._lab_names = lab_names
        else:
            result = pd.DataFrame()
            result._theory_names = []
            result._lab_names = []

        # ── RANK TABLES ──
        rank_marks = None
        rank_sgpa = None

        if total_marks is not None:
            rank_df = total_marks.copy()
            if sgpa is not None:
                rank_df = rank_df.merge(sgpa, on="HTNO")

            # Rank by Total Marks (competition ranking)
            rank_marks = rank_df.sort_values(
                by="Total Marks", ascending=False
            ).reset_index(drop=True)
            rank_marks.insert(0, "Rank", rank_marks["Total Marks"].rank(
                ascending=False, method='min'
            ).astype(int))

            # Rank by SGPA
            if sgpa is not None:
                rank_sgpa = rank_df.sort_values(
                    by="SGPA", ascending=False
                ).reset_index(drop=True)
                rank_sgpa.insert(0, "Rank", rank_sgpa["SGPA"].rank(
                    ascending=False, method='min'
                ).astype(int))

        # ── FAILED STUDENTS ──
        failed_group = pd.DataFrame(columns=["S.No", "HTNO", "Failed Subjects", "Backlog Count"])
        if features["failed_students"] and "GRADE" in df.columns:
            failed = df[df["GRADE"].astype(str).str.strip().isin(["F", "Ab"])]

            if len(failed) > 0:
                failed_group = failed.groupby("HTNO").agg(
                    Failed_Subjects=("SUBJECT", lambda x: ", ".join(x)),
                    Backlog_Count=("SUBJECT", "count")
                ).reset_index()
                failed_group.columns = ["HTNO", "Failed Subjects", "Backlog Count"]
                failed_group.insert(0, "S.No", range(1, len(failed_group) + 1))

        # ── SUBJECT PASS % ──
        subject_pass = pd.DataFrame()
        if features["subject_pass_fail"] and "GRADE" in df.columns:
            total_per_subject = df.groupby("SUBJECT")["HTNO"].nunique().reset_index()
            total_per_subject.columns = ["Subject", "Total Students"]

            passed_per_subject = df[
                ~df["GRADE"].astype(str).str.strip().isin(["F", "Ab"])
            ].groupby("SUBJECT")["HTNO"].nunique().reset_index()
            passed_per_subject.columns = ["Subject", "Passed Students"]

            subject_pass = total_per_subject.merge(passed_per_subject, on="Subject", how="left")
            subject_pass["Passed Students"] = subject_pass["Passed Students"].fillna(0).astype(int)
            subject_pass["Failed Students"] = subject_pass["Total Students"] - subject_pass["Passed Students"]
            subject_pass["Pass %"] = (
                subject_pass["Passed Students"] / subject_pass["Total Students"] * 100
            ).round(2)
            subject_pass["Failure %"] = (100 - subject_pass["Pass %"]).round(2)

            # Add average marks per subject if available
            if has_totals:
                avg_marks = credit_subjects.groupby("SUBJECT")["TOTAL"].agg(
                    ["mean", "max", "min"]
                ).round(2).reset_index()
                avg_marks.columns = ["Subject", "Avg Marks", "Highest", "Lowest"]
                subject_pass = subject_pass.merge(avg_marks, on="Subject", how="left")

        # ── PT ANALYSIS ──
        pt_data = None
        if features["pt_analysis"]:
            pt_reverse = {v: k for k, v in pt_cols.items()}
            pt_df = df.rename(columns=pt_reverse)
            pt_available = [p for p in ["PT1", "PT2", "PT3"] if p in pt_df.columns]
            if pt_available:
                for p in pt_available:
                    pt_df[p] = pd.to_numeric(pt_df[p], errors="coerce")
                pt_data = {
                    "available_series": pt_available,
                    "student_scores": pt_df.groupby("HTNO")[pt_available].mean().round(2).reset_index().to_dict(orient="records"),
                    "subject_scores": pt_df.groupby("SUBJECT")[pt_available].mean().round(2).reset_index().to_dict(orient="records")
                }

        # ═══════════════════════════════════════════════
        # BUILD KPI SUMMARY
        # ═══════════════════════════════════════════════

        total_students = df["HTNO"].nunique()
        total_subjects = df["SUBJECT"].nunique()
        total_records = len(df)

        failed_student_count = failed_group["HTNO"].nunique() if len(failed_group) > 0 and "HTNO" in failed_group.columns else 0
        passed_student_count = total_students - failed_student_count

        total_backlog_records = int(failed_group["Backlog Count"].sum()) if len(failed_group) > 0 and "Backlog Count" in failed_group.columns else 0

        kpi = {
            "total_students": total_students,
            "total_subjects": total_subjects,
            "total_records": total_records,
            "passed_students": passed_student_count,
            "failed_students": failed_student_count,
            "pass_percentage": round(passed_student_count / total_students * 100, 2) if total_students > 0 else 0,
            "total_backlogs": total_backlog_records,
        }

        if has_totals and total_marks is not None:
            kpi["avg_marks"] = round(total_marks["Total Marks"].mean(), 2)
            kpi["highest_marks"] = int(total_marks["Total Marks"].max())
            kpi["lowest_marks"] = int(total_marks["Total Marks"].min())

        if sgpa is not None and len(sgpa) > 0:
            kpi["highest_sgpa"] = float(sgpa["SGPA"].max())
            kpi["avg_sgpa"] = round(float(sgpa["SGPA"].mean()), 2)

        # ═══════════════════════════════════════════════
        # BUILD CHART DATA
        # ═══════════════════════════════════════════════

        chart_data = {
            "subjects": [],
            "overall": {"passed": passed_student_count, "failed": failed_student_count}
        }

        if len(subject_pass) > 0:
            for _, row in subject_pass.iterrows():
                entry = {
                    "name": row["Subject"],
                    "passed": int(row["Passed Students"]),
                    "failed": int(row["Failed Students"]),
                    "pass_pct": float(row["Pass %"])
                }
                if "Avg Marks" in row.index and pd.notna(row["Avg Marks"]):
                    entry["avg_marks"] = float(row["Avg Marks"])
                if "Highest" in row.index and pd.notna(row["Highest"]):
                    entry["highest"] = float(row["Highest"])
                chart_data["subjects"].append(entry)

        # Marks distribution (histogram bins)
        if has_totals and total_marks is not None and len(total_marks) > 0:
            marks = total_marks["Total Marks"]
            bins = [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
            # Adjust bins based on max marks
            max_mark = marks.max()
            if max_mark <= 100:
                bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
            elif max_mark <= 500:
                bins = [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500]
            # Ensure the last bin covers max
            if bins[-1] < max_mark:
                bins.append(int(max_mark) + 1)

            hist, edges = pd.cut(marks, bins=bins, right=True, retbins=True)
            dist = marks.groupby(hist).count()
            chart_data["distribution"] = {
                "labels": [f"{int(edges[i])}-{int(edges[i+1])}" for i in range(len(edges)-1)],
                "counts": [int(v) for v in dist.values]
            }

        # Top 10 performers
        if rank_marks is not None and len(rank_marks) > 0:
            top10 = rank_marks.head(10)
            chart_data["top_performers"] = {
                "labels": top10["HTNO"].tolist(),
                "marks": top10["Total Marks"].tolist()
            }
            if "SGPA" in top10.columns:
                chart_data["top_performers"]["sgpa"] = top10["SGPA"].tolist()

        # SGPA distribution
        if sgpa is not None and len(sgpa) > 0:
            sgpa_vals = sgpa["SGPA"]
            sgpa_bins = [0, 2, 4, 5, 6, 7, 8, 9, 10]
            sgpa_labels_list = ["0-2", "2-4", "4-5", "5-6", "6-7", "7-8", "8-9", "9-10"]
            sgpa_hist = pd.cut(sgpa_vals, bins=sgpa_bins, right=True)
            sgpa_dist = sgpa_vals.groupby(sgpa_hist).count()
            chart_data["sgpa_distribution"] = {
                "labels": sgpa_labels_list,
                "counts": [int(v) for v in sgpa_dist.values]
            }

        # Subject failure analysis
        if len(subject_pass) > 0:
            chart_data["failure_analysis"] = {
                "labels": subject_pass["Subject"].tolist(),
                "failed_counts": subject_pass["Failed Students"].astype(int).tolist(),
                "failure_pct": subject_pass["Failure %"].tolist()
            }

        # PT series comparison
        if pt_data:
            chart_data["pt_series"] = pt_data

        # ═══════════════════════════════════════════════
        # PACKAGE RESULTS
        # ═══════════════════════════════════════════════

        results = {
            "result": result,
            "failed": failed_group,
            "rank_marks": rank_marks,
            "rank_sgpa": rank_sgpa,
            "subject_pass": subject_pass,
            "features": features,
            "pt_data": pt_data
        }

        return results, chart_data, kpi, metadata, features, None

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, None, None, None, None, f"Processing error: {str(e)}"


def get_sheet_names(path):
    """Get worksheet names from an Excel file."""
    try:
        xl = pd.ExcelFile(path)
        return xl.sheet_names
    except Exception:
        return []


def build_result_html(result, has_sgpa=True):
    """Build custom HTML table with grouped Subjects/Labs headers (preserved from original)."""
    if result is None or len(result) == 0:
        return ""

    theory_names = getattr(result, '_theory_names', [])
    lab_names = getattr(result, '_lab_names', [])
    cols = list(result.columns)

    # Build the group header row
    group_row = '<tr>'
    group_row += '<th rowspan="2">S.No</th>'
    group_row += '<th rowspan="2">HTNO</th>'
    if theory_names:
        group_row += f'<th colspan="{len(theory_names)}" style="text-align:center;background:linear-gradient(135deg,#023e8a,#0077b6);color:#fff;font-size:1rem;letter-spacing:1px;">📚 Subjects</th>'
    if lab_names:
        group_row += f'<th colspan="{len(lab_names)}" style="text-align:center;background:linear-gradient(135deg,#0096c7,#48cae4);color:#fff;font-size:1rem;letter-spacing:1px;">🔬 Labs</th>'
    group_row += '<th rowspan="2">Total Marks</th>'
    group_row += '<th rowspan="2">Overall %</th>'
    if has_sgpa and "SGPA" in cols:
        group_row += '<th rowspan="2">SGPA</th>'
    group_row += '</tr>'

    # Build the subject names header row
    names_row = '<tr>'
    for name in theory_names + lab_names:
        names_row += f'<th>{name}</th>'
    names_row += '</tr>'

    # Build data rows
    data_rows = ''
    for _, row in result.iterrows():
        data_rows += '<tr>'
        for col in cols:
            val = row[col]
            if pd.isna(val):
                val = '-'
            elif isinstance(val, float) and val == int(val):
                val = int(val)
            data_rows += f'<td>{val}</td>'
        data_rows += '</tr>'

    return f'<table class="table table-bordered"><thead>{group_row}{names_row}</thead><tbody>{data_rows}</tbody></table>'


def generate_detailed_excel(results, kpi, metadata):
    """Generate multi-sheet Results Excel workbook."""
    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Dashboard Summary
        summary_data = {
            "Metric": [],
            "Value": []
        }
        for key, val in kpi.items():
            label = key.replace("_", " ").title()
            summary_data["Metric"].append(label)
            summary_data["Value"].append(val)

        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Dashboard Summary", index=False)

        # Sheet 2: Student Results
        result = results.get("result")
        if result is not None and len(result) > 0:
            result.to_excel(writer, sheet_name="Student Results", index=False)

        # Sheet 3: Rank by Marks
        rank_marks = results.get("rank_marks")
        if rank_marks is not None and len(rank_marks) > 0:
            rank_marks.to_excel(writer, sheet_name="Rank by Marks", index=False)

        # Sheet 4: Rank by SGPA
        rank_sgpa = results.get("rank_sgpa")
        if rank_sgpa is not None and len(rank_sgpa) > 0:
            rank_sgpa.to_excel(writer, sheet_name="Rank by SGPA", index=False)

        # Sheet 5: Subject Analysis
        subject_pass = results.get("subject_pass")
        if subject_pass is not None and len(subject_pass) > 0:
            subject_pass.to_excel(writer, sheet_name="Subject Analysis", index=False)

        # Sheet 6: Failed Students
        failed = results.get("failed")
        if failed is not None and len(failed) > 0:
            failed.to_excel(writer, sheet_name="Failed Students", index=False)

    output.seek(0)
    return output

# Alias for backward compatibility
generate_asra_excel = generate_detailed_excel


# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def index():
    tables = {}
    chart_data = None
    kpi = None
    metadata = None
    features = None
    error_msg = None
    sheet_names = None

    campus = request.form.get("campus") or request.args.get("campus") or session.get("campus", "AVIH")
    session["campus"] = campus

    if request.method == "POST":

        file = request.files.get("file")
        if not file or file.filename == '':
            error_msg = "No file selected."
        else:
            # Validate file extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ['.xlsx', '.xls']:
                error_msg = "Unsupported file format. Please upload .xlsx or .xls files."
            else:
                # Session-based filename to avoid conflicts
                session_id = session.get('session_id', str(uuid.uuid4()))
                session['session_id'] = session_id

                safe_filename = f"{session_id}_{file.filename}"
                # Sanitize filename
                safe_filename = re.sub(r'[^\w\.\-]', '_', safe_filename)
                path = os.path.join(UPLOAD_FOLDER, safe_filename)
                file.save(path)

                # Check for sheet selection
                selected_sheet = request.form.get("sheet", None)
                if selected_sheet:
                    try:
                        selected_sheet = int(selected_sheet)
                    except ValueError:
                        pass  # Keep as string (sheet name)

                sheets = get_sheet_names(path)
                if len(sheets) > 1 and selected_sheet is None:
                    # Return sheet selection UI
                    sheet_names = sheets
                    session['pending_file'] = path
                    session['original_filename'] = file.filename
                else:
                    sheet_idx = selected_sheet if selected_sheet is not None else 0
                    results, chart_data_dict, kpi, metadata, features, err = process_file_dynamic(path, sheet_idx)

                    if err:
                        error_msg = err
                    elif results:
                        result = results["result"]
                        failed = results["failed"]
                        rank_marks = results["rank_marks"]
                        rank_sgpa = results["rank_sgpa"]
                        subject_pass = results["subject_pass"]

                        has_sgpa = results["features"]["sgpa_ranking"] and rank_sgpa is not None

                        # Build HTML tables (preserving original format)
                        tables["result"] = build_result_html(result, has_sgpa)
                        tables["failed"] = failed.to_html(classes="table table-bordered", index=False) if len(failed) > 0 else "<p>No failed students found.</p>"
                        tables["rank_marks"] = rank_marks.to_html(classes="table table-bordered", index=False) if rank_marks is not None else ""
                        if has_sgpa:
                            tables["rank_sgpa"] = rank_sgpa.to_html(classes="table table-bordered", index=False)
                        else:
                            tables["rank_sgpa"] = "<p>SGPA data not available in this workbook.</p>"
                        tables["subject_pass"] = subject_pass.to_html(classes="table table-bordered", index=False) if len(subject_pass) > 0 else ""

                        chart_data = chart_data_dict

                        # Save output Excel (session-specific)
                        output_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_Detailed_Results.xlsx")
                        excel_bytes = generate_detailed_excel(results, kpi, metadata)
                        with open(output_path, 'wb') as f:
                            f.write(excel_bytes.read())
                        session['output_file'] = output_path

                        # Also save as output.xlsx for backward compatibility
                        if result is not None and len(result) > 0:
                            result.to_excel("uploads/output.xlsx", index=False)

    # Handle sheet selection POST
    elif request.method == "GET" and 'pending_file' in session:
        # Clear pending if no sheet selected
        pass

    # Handle sheet selection form
    if request.method == "POST" and request.form.get("sheet_select"):
        path = session.get('pending_file')
        if path and os.path.exists(path):
            sheet_idx = request.form.get("sheet_select")
            try:
                sheet_idx = int(sheet_idx)
            except ValueError:
                pass

            results, chart_data_dict, kpi, metadata, features, err = process_file_dynamic(path, sheet_idx)

            if err:
                error_msg = err
            elif results:
                result = results["result"]
                failed = results["failed"]
                rank_marks = results["rank_marks"]
                rank_sgpa = results["rank_sgpa"]
                subject_pass = results["subject_pass"]
                has_sgpa = results["features"]["sgpa_ranking"] and rank_sgpa is not None

                tables["result"] = build_result_html(result, has_sgpa)
                tables["failed"] = failed.to_html(classes="table table-bordered", index=False) if len(failed) > 0 else "<p>No failed students found.</p>"
                tables["rank_marks"] = rank_marks.to_html(classes="table table-bordered", index=False) if rank_marks is not None else ""
                tables["rank_sgpa"] = rank_sgpa.to_html(classes="table table-bordered", index=False) if has_sgpa else "<p>SGPA data not available.</p>"
                tables["subject_pass"] = subject_pass.to_html(classes="table table-bordered", index=False) if len(subject_pass) > 0 else ""

                chart_data = chart_data_dict

                session_id = session.get('session_id', str(uuid.uuid4()))
                output_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_Detailed_Results.xlsx")
                excel_bytes = generate_detailed_excel(results, kpi, metadata)
                with open(output_path, 'wb') as f:
                    f.write(excel_bytes.read())
                session['output_file'] = output_path

                if result is not None and len(result) > 0:
                    result.to_excel("uploads/output.xlsx", index=False)

            # Clear pending state
            session.pop('pending_file', None)
            sheet_names = None

    return render_template(
        "index.html",
        tables=tables,
        chart_data=json.dumps(chart_data) if chart_data else "null",
        kpi=kpi,
        metadata=metadata,
        features=features,
        error_msg=error_msg,
        sheet_names=sheet_names,
        campus=campus
    )


@app.route("/download")
def download():
    """Download standard output.xlsx."""
    if 'output_file' in session:
        path = "uploads/output.xlsx"
        if os.path.exists(path):
            return send_file(path, as_attachment=True)
    return "Please upload and analyze an Excel file first.", 400


@app.route("/download_detailed")
@app.route("/download_asra")
def download_detailed():
    """Download multi-sheet Detailed Results Excel."""
    output_path = session.get('output_file')
    if output_path and os.path.exists(output_path):
        campus = session.get('campus', 'Detailed')
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"{campus}_Results_Analysis.xlsx"
        )
    return "Please upload and analyze an Excel file first.", 400


@app.route("/demo")
def demo():
    """Demo route to preview full dashboard with sample dataset."""
    sample_file = os.path.join(UPLOAD_FOLDER, "Q6-66-III B.Tech. I Semester (R22) Regular.xlsx")
    tables = {}
    chart_data = None
    kpi = None
    metadata = None
    features = None

    if os.path.exists(sample_file):
        results, chart_data_dict, kpi, metadata, features, err = process_file_dynamic(sample_file, 0)
        if results:
            result = results["result"]
            failed = results["failed"]
            rank_marks = results["rank_marks"]
            rank_sgpa = results["rank_sgpa"]
            subject_pass = results["subject_pass"]
            has_sgpa = results["features"]["sgpa_ranking"] and rank_sgpa is not None

            tables["result"] = build_result_html(result, has_sgpa)
            tables["failed"] = failed.to_html(classes="table table-bordered", index=False) if len(failed) > 0 else "<p>No failed students found.</p>"
            tables["rank_marks"] = rank_marks.to_html(classes="table table-bordered", index=False) if rank_marks is not None else ""
            tables["rank_sgpa"] = rank_sgpa.to_html(classes="table table-bordered", index=False) if has_sgpa else "<p>SGPA data not available.</p>"
            tables["subject_pass"] = subject_pass.to_html(classes="table table-bordered", index=False) if len(subject_pass) > 0 else ""
            chart_data = chart_data_dict

    return render_template(
        "index.html",
        tables=tables,
        chart_data=json.dumps(chart_data) if chart_data else "null",
        kpi=kpi,
        metadata=metadata,
        features=features,
        error_msg=None,
        sheet_names=None,
        campus="AVIH"
    )


if __name__ == "__main__":
    app.run(debug=True)

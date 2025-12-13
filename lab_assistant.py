import streamlit as st
import anthropic
import base64
import pandas as pd
import os
import json
import zipfile
import time
import re
from docx import Document
from io import BytesIO

# --- 1. PAGE SETUP (MUST BE FIRST) ---
st.set_page_config(
    page_title="Pre-IB Lab Grader", 
    page_icon="🧪", 
    layout="wide"
)

# --- 2. CONFIGURATION & SECRETS ---
if "ANTHROPIC_API_KEY" in st.secrets:
    API_KEY = st.secrets["ANTHROPIC_API_KEY"]
elif "ANTHROPIC_API_KEY" in os.environ:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
else:
    st.error("🚨 API Key not found!")
    st.info("On Streamlit Cloud, add your key to the 'Secrets' settings.")
    st.stop()

MODEL_NAME = "claude-sonnet-4-20250514"

# --- 3. HARDCODED RUBRIC ---
PRE_IB_RUBRIC = """TOTAL: 100 POINTS (10 pts per section)

1. FORMATTING (10 pts) [LENIENT]:
- Criteria: Third-person passive voice, professional tone.
- Note: Score high (9-10) unless "I/We" is used consistently.

2. INTRODUCTION (10 pts):
- Criteria: Clear objective, background theory, balanced equations.

3. HYPOTHESIS (10 pts):
- Criteria: Specific prediction with scientific justification.

4. VARIABLES (10 pts) [SPECIFIC RULE]:
- Criteria: IV (units/range), DV (method), 3+ Controlled Variables.
- SCORING RULE: If control variables are listed but not explained/justified properly, score exactly 8/10.

5. PROCEDURES (10 pts) [SPECIFIC RULE]:
- Criteria: Numbered steps, specific quantities, safety.
- SCORING RULE: A missing diagram is a MINOR deduction (-0.5 points). Do not penalize heavily for this.

6. RAW DATA (10 pts) [NO UNCERTAINTIES REQUIRED]:
- Criteria: Qualitative observations, clear tables, units, consistent significant figures.
- NOTE: Pre-IB students are NOT required to include uncertainties (±). Do NOT deduct for missing uncertainties.
- CRITICAL: Deduct if significant figures are inconsistent (e.g., 10.5g in one row, 10g in the next).

7. DATA ANALYSIS (10 pts) [SIG FIGS CRITICAL]:
- Criteria: Sample calculation shown, graphs (axes/trendlines), R² value.
- INTERMEDIATE STEPS: Students may keep extra significant figures in intermediate steps to avoid rounding errors.
- FINAL ANSWER: The final result MUST be rounded to the correct significant figures based on the data.
- DEDUCTIONS: 
  * Lose 0.5 pts if some correct sig figs were used (partial effort).
  * Lose 1.0 pt if NO attention was paid to sig figs (e.g., writing 12.333333).

8. CONCLUSION (10 pts):
- Criteria: Supported/Refuted statement, data evidence, literature comparison.

9. EVALUATION (10 pts) [FORMULAIC SCORING]:
- 6 POINTS: Describes 2 Systematic AND 2 Random errors.
- +2 POINTS: Explains the impact of these errors on data.
- +2 POINTS: Suggests realistic improvements.
- Note: If they have fewer than 2 of each error type, deduct from the base 6 points accordingly.

10. REFERENCES (10 pts) [LENIENT]:
- Criteria: Sources listed and cited.
- Note: Ignore minor punctuation errors. Score 9-10 if sources are present and reliable.
"""

# --- 4. SYSTEM PROMPT ---
SYSTEM_PROMPT = """You are an expert Pre-IB Chemistry Lab Grader. 
Your goal is to grade student lab reports according to the specific rules below.

### 🧠 SCORING ALGORITHMS (CRITICAL):

1.  **VARIABLES (Section 4):**
    * **Rule:** If they listed the Control Variables but didn't explain WHY or HOW they were controlled, give them **8/10**.

2.  **PROCEDURES (Section 5):**
    * **Rule:** If the ONLY thing missing is the diagram, the score should be **9.5/10**.

3.  **DATA ANALYSIS (Section 7) - CALCULATION CHECK:**
    * **Intermediate vs. Final:** Students are allowed (and encouraged) to keep extra digits in intermediate steps. ONLY grade the sig figs of the **final answer**.
    * **Deduction Logic:**
        * If they mostly got it right but missed one or two: **Deduct 0.5 points**.
        * If they completely ignored sig figs (e.g., writing 8.33333333): **Deduct 1.0 point**.

4.  **EVALUATION (Section 9) - USE THIS MATH:**
    * Start with **0**.
    * Add **up to 6 points** for identifying errors (Need **2 Systematic + 2 Random**).
    * Add **2 points** if they explain the *impact* of these errors.
    * Add **2 points** if they explain *improvements*.

5.  **LENIENCY (Sections 1 & 10):**
    * Be generous on Formatting and References. High scores default unless major errors exist.

### 📝 FEEDBACK INSTRUCTIONS (SUMMARY STYLE):
1.  **Summarize Evidence:** Do NOT quote the student directly. Instead, summarize what they did in your own words.
    * *Good:* "You provided a sample calculation for density. While you kept extra digits in the intermediate steps (which is correct), your final answer had 5 sig figs instead of the required 3."
2.  **Structure:** "✅ Strengths" and "⚠️ Improvements" for every section.

### OUTPUT FORMAT:
Please strictly use the following format.

SCORE: [Total Points]/100
STUDENT: [Filename]
---
**📊 OVERALL SUMMARY & VISUAL ANALYSIS:**
* [1-2 sentences on quality]
* [Critique of graphs/images]

**📝 DETAILED RUBRIC BREAKDOWN:**

**1. FORMATTING: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**2. INTRODUCTION: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**3. HYPOTHESIS: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**4. VARIABLES: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**5. PROCEDURES: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**6. RAW DATA: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**7. DATA ANALYSIS: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors; specifically mention calculation sig figs]

**8. CONCLUSION: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**9. EVALUATION: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

**10. REFERENCES: [Score]/10**
* **✅ Strengths:** [Summary of good work]
* **⚠️ Improvements:** [Summary of errors]

---
**💡 TOP 3 ACTIONABLE STEPS FOR NEXT TIME:**
1. [Step 1]
2. [Step 2]
3. [Step 3]
"""

# Initialize Session State
if 'saved_sessions' not in st.session_state:
    st.session_state.saved_sessions = {}
if 'current_results' not in st.session_state:
    st.session_state.current_results = []
if 'current_session_name' not in st.session_state:
    st.session_state.current_session_name = "New Grading Session"

client = anthropic.Anthropic(api_key=API_KEY)

# --- 5. HELPER FUNCTIONS ---
def encode_file(uploaded_file):
    try:
        uploaded_file.seek(0)
        return base64.b64encode(uploaded_file.read()).decode('utf-8')
    except Exception as e:
        st.error(f"Error encoding file: {e}")
        return None

def get_media_type(filename):
    ext = filename.lower().split('.')[-1]
    media_types = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'pdf': 'application/pdf'
    }
    return media_types.get(ext, 'image/jpeg')

def extract_text_from_docx(file):
    try:
        doc = Document(file)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Error reading .docx file: {e}"

def extract_images_from_docx(file):
    images = []
    try:
        file.seek(0)
        with zipfile.ZipFile(file) as z:
            for filename in z.namelist():
                if filename.startswith('word/media/') and filename.split('.')[-1].lower() in ['png', 'jpg', 'jpeg', 'gif']:
                    img_data = z.read(filename)
                    b64_img = base64.b64encode(img_data).decode('utf-8')
                    ext = filename.split('.')[-1].lower()
                    images.append({
                        "type": "image",
                        "source": {
                            "type": "base64", 
                            "media_type": f"image/{'jpeg' if ext=='jpg' else ext}", 
                            "data": b64_img
                        }
                    })
    except Exception as e:
        print(f"Image extraction failed: {e}")
    return images

def process_uploaded_files(uploaded_files):
    final_files = []
    IGNORED_FILES = {'.ds_store', 'desktop.ini', 'thumbs.db', '__macosx'}
    VALID_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'docx'}
    
    file_counts = {"pdf": 0, "docx": 0, "image": 0, "ignored": 0}

    for file in uploaded_files:
        file_name_lower = file.name.lower()
        if file_name_lower in IGNORED_FILES or file_name_lower.startswith('._'):
            continue

        if file_name_lower.endswith('.zip'):
            try:
                with zipfile.ZipFile(file) as z:
                    for filename in z.namelist():
                        clean_name = filename.lower()
                        if any(x in clean_name for x in IGNORED_FILES) or filename.startswith('.'): continue
                        ext = clean_name.split('.')[-1]
                        if ext in VALID_EXTENSIONS:
                            file_bytes = z.read(filename)
                            virtual_file = BytesIO(file_bytes)
                            virtual_file.name = os.path.basename(filename)
                            final_files.append(virtual_file)
                            if ext == 'docx': file_counts['docx'] += 1
                            elif ext == 'pdf': file_counts['pdf'] += 1
                            else: file_counts['image'] += 1
            except Exception as e:
                st.error(f"Error unzipping {file.name}: {e}")
        else:
            ext = file_name_lower.split('.')[-1]
            if ext in VALID_EXTENSIONS:
                final_files.append(file)
                if ext == 'docx': file_counts['docx'] += 1
                elif ext == 'pdf': file_counts['pdf'] += 1
                else: file_counts['image'] += 1
            else:
                file_counts['ignored'] += 1
            
    return final_files, file_counts

# --- MATH CHECKER FUNCTION ---
def recalculate_total_score(text):
    try:
        pattern = r"\d+\.\s+[A-Z\s]+:\s+([\d\.]+)/10"
        matches = re.findall(pattern, text)
        if matches:
            total_score = sum(float(m) for m in matches)
            if total_score.is_integer():
                total_score = int(total_score)
            else:
                total_score = round(total_score, 1)
            text = re.sub(r"SCORE:\s*[\d\.]+/100", f"SCORE: {total_score}/100", text, count=1)
    except Exception as e:
        print(f"Error recalculating score: {e}")
    return text

def grade_submission(file):
    ext = file.name.split('.')[-1].lower()
    
    if ext == 'docx':
        text_content = extract_text_from_docx(file)
        user_message = [
            {
                "type": "text",
                "text": (
                    f"Please grade this lab report based on the Pre-IB rubric below.\n"
                    f"Note: This is a converted Word Document. Attached is the text followed by images.\n\n"
                    f"--- RUBRIC START ---\n{PRE_IB_RUBRIC}\n--- RUBRIC END ---\n\n"
                    f"STUDENT TEXT:\n{text_content}"
                )
            }
        ]
        images = extract_images_from_docx(file)
        if images:
            user_message.extend(images)
    else:
        base64_data = encode_file(file)
        if not base64_data: return "Error processing file."
        media_type = get_media_type(file.name)
        
        user_message = [
            {
                "type": "text",
                "text": (
                    f"Please grade this lab report based on the Pre-IB rubric below.\n\n"
                    f"--- RUBRIC START ---\n{PRE_IB_RUBRIC}\n--- RUBRIC END ---\n\n"
                    f"INSTRUCTIONS:\n"
                    f"1. Provide a specific score out of 10 for each of the 10 sections.\n"
                    f"2. Sum them for a total out of 100.\n"
                    f"3. Be strict about significant figures, error analysis, and citations."
                )
            },
            {
                "type": "document" if media_type == 'application/pdf' else "image",
                "source": {"type": "base64", "media_type": media_type, "data": base64_data}
            }
        ]

    max_retries = 3
    retry_delay = 5 
    
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=3500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}]
            )
            raw_text = response.content[0].text
            corrected_text = recalculate_total_score(raw_text)
            return corrected_text
            
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            return "⚠️ Error: Rate limit exceeded."
        except Exception as e:
            return f"⚠️ Error: {str(e)}"

def parse_score(text):
    try:
        lines = text.split('\n')
        for line in lines:
            if "SCORE:" in line:
                return line.split("SCORE:")[1].strip()
    except:
        pass
    return "N/A"

# --- SMART FORMATTER FOR WORD ---
def write_markdown_to_docx(doc, text):
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith('### '):
            doc.add_heading(line.replace('### ', '').strip(), level=3)
            continue
        
        if line.startswith('**') and line.endswith('**') and len(line) < 60:
            p = doc.add_paragraph()
            run = p.add_run(line.replace('**', ''))
            run.bold = True
            continue

        if line.startswith('* ') or line.startswith('- '):
            p = doc.add_paragraph(style='List Bullet')
            content = line[2:] 
        else:
            p = doc.add_paragraph()
            content = line

        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                clean_text = part[2:-2]
                run = p.add_run(clean_text)
                run.bold = True
            else:
                p.add_run(part)

def create_master_doc(results, session_name):
    doc = Document()
    doc.add_heading(f"Lab Report Grades: {session_name}", 0)
    for item in results:
        doc.add_heading(item['Filename'], level=1)
        doc.add_heading(f"Score: {item['Score']}", level=2)
        write_markdown_to_docx(doc, item['Feedback'])
        doc.add_page_break()
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()

def create_zip_bundle(results):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for item in results:
            doc = Document()
            doc.add_heading(f"Feedback: {item['Filename']}", 0)
            doc.add_heading(f"Score: {item['Score']}", level=1)
            write_markdown_to_docx(doc, item['Feedback'])
            doc_buffer = BytesIO()
            doc.save(doc_buffer)
            safe_name = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
            z.writestr(safe_name, doc_buffer.getvalue())
    return zip_buffer.getvalue()

def display_results_ui():
    if not st.session_state.current_results:
        return

    st.divider()
    st.subheader(f"📊 Results: {st.session_state.current_session_name}")
    
    df = pd.DataFrame(st.session_state.current_results)
    
    csv_df = df[["Filename", "Score", "Feedback"]]
    csv_data = csv_df.to_csv(index=False).encode('utf-8')
    
    master_doc_data = create_master_doc(st.session_state.current_results, st.session_state.current_session_name)
    zip_data = create_zip_bundle(st.session_state.current_results)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📄 Master Doc (All-in-One)", master_doc_data, f'{st.session_state.current_session_name}_Master.docx', "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
    with col2:
        st.download_button("📦 Student Bundle (.zip)", zip_data, f'{st.session_state.current_session_name}_Students.zip', "application/zip", use_container_width=True)
    with col3:
        st.download_button("📊 Gradebook (.csv)", csv_data, f'{st.session_state.current_session_name}_Grades.csv', "text/csv", use_container_width=True)

    tab1, tab2 = st.tabs(["📊 Gradebook View", "📝 Detailed Feedback"])
    with tab1:
        st.dataframe(df[["Filename", "Score"]], use_container_width=True)
    with tab2:
        for item in st.session_state.current_results:
            with st.expander(f"📄 {item['Filename']} (Score: {item['Score']})"):
                st.markdown(item['Feedback'])

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("💾 History Manager")
    save_name = st.text_input("Session Name", placeholder="e.g. Period 3 - Kinetics")
    if st.button("💾 Save Session"):
        if st.session_state.current_results:
            st.session_state.saved_sessions[save_name] = st.session_state.current_results
            st.success(f"Saved '{save_name}'!")
        else:
            st.warning("No results to save yet.")
            
    st.divider()
    if st.session_state.saved_sessions:
        st.subheader("📂 Load Session")
        selected_session = st.selectbox("Select Batch", list(st.session_state.saved_sessions.keys()))
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Load"):
                st.session_state.current_results = st.session_state.saved_sessions[selected_session]
                st.session_state.current_session_name = selected_session
                st.rerun()
        with col2:
            if st.button("🗑️ Delete"):
                del st.session_state.saved_sessions[selected_session]
                st.rerun()
    st.divider()
    with st.expander("View Grading Criteria"):
        st.text(PRE_IB_RUBRIC)
    st.caption(f"🤖 Model: {MODEL_NAME}")

# --- 7. MAIN INTERFACE ---
st.title("🧪 Pre-IB Lab Grader")
st.caption(f"Current Session: **{st.session_state.current_session_name}**")

st.info("💡 **Tip:** To upload a folder, open it, press `Ctrl+A` (Select All), and drag everything here.")

raw_files = st.file_uploader(
    "📂 Upload Reports (PDF, Word, Images, ZIP)", 
    type=['pdf', 'docx', 'png', 'jpg', 'jpeg', 'zip'], 
    accept_multiple_files=True
)

processed_files = []
if raw_files:
    processed_files, counts = process_uploaded_files(raw_files)
    if len(processed_files) > 0:
        st.success(f"✅ Found **{len(processed_files)}** valid reports.")
        st.caption(f"📄 PDFs: {counts['pdf']} | 📝 Word Docs: {counts['docx']} | 🖼️ Images: {counts['image']}")
        if counts['ignored'] > 0:
            st.warning(f"⚠️ {counts['ignored']} files were ignored (unsupported format).")
    else:
        if raw_files:
            st.warning("No valid PDF, Word, or Image files found.")

if st.button("🚀 Grade Reports", type="primary", disabled=not processed_files):
    
    st.write("---")
    progress = st.progress(0)
    status = st.empty()
    
    new_results = []
    
    for i, file in enumerate(processed_files):
        status.markdown(f"**Grading:** `{file.name}`...")
        
        feedback = grade_submission(file)
        score = parse_score(feedback)
        
        new_results.append({
            "Filename": file.name,
            "Score": score,
            "Feedback": feedback
        })
        progress.progress((i + 1) / len(processed_files))
        
        time.sleep(1) 

    st.session_state.current_results = new_results
    status.success("✅ Grading Complete! Scrolling down...")
    progress.empty()

# --- 8. PERSISTENT DISPLAY ---
if st.session_state.current_results:
     display_results_ui()
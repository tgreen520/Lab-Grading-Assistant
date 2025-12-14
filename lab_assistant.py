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

GENERAL PRINCIPLE: Award partial credit when students make genuine attempts to follow the rubric, even if execution is imperfect. Recognize effort and partial understanding.

1. FORMATTING (10 pts):
- Criteria: Third-person passive voice, professional tone, superscripts/subscripts used correctly IN THE BODY TEXT.
- DEDUCTIONS: 
  * Superscripts/Subscripts IN BODY TEXT ONLY: Count the errors in paragraphs and written explanations. 
    * If 0-2 errors: **-0 pts** (Ignore).
    * If >2 errors: **-1.0 pt**.
  * **IMPORTANT:** Do NOT deduct points for superscript/subscript errors in graph titles, axis labels, or data tables.
  * Consistent use of "I/We": Deduct heavily.
  * NOTE: Do NOT deduct points for minor layout inconsistencies (margins, fonts, spacing, indentation).
- PARTIAL CREDIT: Award partial points if student shows awareness of professional tone but has some lapses.

2. INTRODUCTION (10 pts):
- Criteria: Clear objective, background theory, balanced equations.
- PARTIAL CREDIT: Award points proportionally (e.g., clear objective present: 3-4 pts).

3. HYPOTHESIS (10 pts):
- Criteria: Specific prediction with scientific justification.
- PARTIAL CREDIT: Prediction stated but lacks specificity: 5-7 pts.

4. VARIABLES (10 pts):
- Criteria: IV (units/range), DV (method), 3+ Controlled Variables.
- **ACCEPTABLE FORMATS:** Variables may be presented in paragraph form OR in a data table format. BOTH formats are equally acceptable.
- **CRITICAL TABLE DETECTION:** Check the entire document for tables listing "Variable," "Independent," "Dependent," "Control."
- **SCORING GUIDE:**
  * **10/10:** IV + DV + 3+ Control Variables with clear explanations/descriptions (table or paragraph format)
  * **9/10:** IV + DV + 3+ Control Variables clearly identified in a table OR with minimal explanations
  * **8/10:** 3+ Control variables listed but not explained in detail
  * **7/10:** 2 Control variables listed
  * **6/10:** Only IV and DV properly identified
  * **0-5/10:** Incomplete or missing.
- **RULE:** If you find a table listing IV + DV + 3 Controls, the MINIMUM score is 9/10.

5. PROCEDURES (10 pts):
- Criteria: Numbered steps, specific quantities, safety.
- SCORING RULE: A missing diagram is a MINOR deduction (-0.5 points).

6. RAW DATA (10 pts) [NO UNCERTAINTIES REQUIRED]:
- Criteria: Qualitative observations, clear tables, units, consistent significant figures.
- NOTE: Pre-IB students are NOT required to include uncertainties (±). Do NOT deduct for missing uncertainties.
- CRITICAL: Deduct if significant figures are inconsistent.
- FORMATTING: Do NOT deduct points for minor formatting issues in tables (borders, alignment, font). Focus on data clarity and units.

7. DATA ANALYSIS (10 pts) [SIG FIGS CRITICAL]:
- Criteria: Sample calculation shown, graphs (axes/trendlines), R² value.
- SIG FIGS: Students may keep extra digits in intermediate steps. ONLY the final result must be rounded correctly.
- DEDUCTIONS: -0.5 for partial effort, -1.0 for zero attention to sig figs.

8. CONCLUSION (10 pts):
- Criteria: Statement of support/refutation, specific data evidence.
- CRITICAL REQUIREMENT: Must include specific comparisons to PUBLISHED LITERATURE (theoretical values or accepted standards).
- PARTIAL CREDIT: Award points for conclusions that reference data even if literature comparison is weak or missing.

9. EVALUATION (10 pts) [UPDATED FORMULAIC SCORING]:
- 5 POINTS: Lists at least 4 sources of error (any combination of systematic/random).
- +1 POINT: Specifically identifies which errors are systematic vs. random.
- UP TO +2 POINTS: Explains the impact of these errors on data. (Award 1 pt for weak/partial explanation).
- UP TO +2 POINTS: Suggests realistic improvements. (Award 1 pt for weak/partial suggestions).

10. REFERENCES (10 pts):
- Criteria: Sources listed and cited.
- **AUTOMATIC SCORING LOGIC (The "9-Point Floor"):**
  * **CHECK:** Does the student have **3+ credible sources**?
  * **IF YES:** The score MUST be between 9.0 and 10.0.
    * **10/10:** Perfect or near-perfect APA formatting.
    * **9.5/10:** Minor APA formatting issues (italics, punctuation, capitalization).
    * **9.0/10:** Significant APA formatting issues (but sources are present and resemble APA).
  * **IF NO:** (Fewer than 3 sources) -> Grade normally (usually 7-8 or lower).
"""

# --- 4. SYSTEM PROMPT ---
SYSTEM_PROMPT = """You are an expert Pre-IB Chemistry Lab Grader. 
Your goal is to grade student lab reports according to the specific rules below.

### ⚖️ CONSISTENCY & BIAS ELIMINATION PROTOCOL (CRITICAL):
* **Zero Drift:** You must grade every paper with EXACTLY the same standard.
* **Rigid Adherence to Deductions:** Apply the specific point deductions with mathematical precision.

### 🧠 SCORING ALGORITHMS:

1.  **FORMATTING (Section 1):**
    * **Layout:** Do NOT deduct points for minor layout/formatting inconsistencies. Ignore spacing/margin issues.
    * **Subscripts/Superscripts - BODY TEXT ONLY:** Count errors ONLY in paragraphs.
        * If 0-2 errors: **-0 pts** (Ignore).
        * If >2 errors: **-1.0 pt**.

2.  **VARIABLES (Section 4) - ⚠️ CRITICAL TABLE DETECTION:**
    * **MANDATORY:** Scan the entire document for tables containing "Variable," "Independent," "Dependent," "Control."
    * **RULE:** If you find a table with 1 IV + 1 DV + 3+ Controls, score it **9-10/10**.
    * **ACCEPTABLE FORMATS:** Variables may be presented in paragraph form OR in a table. Both are valid.
    
3.  **RAW DATA (Section 6):**
    * **Formatting:** Do NOT deduct points for table aesthetics (borders, shading, alignment). Only deduct if data is illegible or units/sig figs are wrong.
    * **No Uncertainties:** Do not deduct for missing ± values.

4.  **DATA ANALYSIS (Section 7) - CALCULATION CHECK:**
    * **Intermediate vs. Final:** Students are allowed to keep extra digits in intermediate steps. ONLY grade the sig figs of the **final answer**.
    * **Deduction Logic:**
        * Mostly right but missed one/two: **-0.5 points**.
        * Completely ignored sig figs: **-1.0 point**.

5.  **CONCLUSION (Section 8) - LITERATURE CHECK:**
    * **Requirement:** The student MUST compare their result to a published literature value or theory.
    * **Evaluation:** If they simply say "My results matched theory" without citing a specific value or source, this is insufficient.

6.  **EVALUATION (Section 9) - UPDATED FORMULA:**
    * Start with **0**.
    * Add **5 points** if they list at least **4 sources of error**.
    * Add **1 point** if they identify systematic vs. random.
    * Add **up to 2 points** for explaining *impact* (1 pt for weak explanation).
    * Add **up to 2 points** for explaining *improvements* (1 pt for weak explanation).

7.  **REFERENCES (Section 10) - THE 3+ SOURCE RULE:**
    * **STEP 1:** Count the credible sources (websites, journals, books).
    * **STEP 2 (If < 3 sources):** Score normally (usually 7-8 or lower).
    * **STEP 3 (If 3+ sources present):** You MUST score this section **9.0 or higher**.
        * **10/10:** Formatting is perfect.
        * **9.5/10:** Formatting has minor errors (punctuation, italics).
        * **9.0/10:** Formatting has significant errors, but it still resembles APA style.
    * **CRITICAL:** Do NOT give 8.5 or lower if there are 3+ sources. The minimum is 9.0.

### 📝 FEEDBACK INSTRUCTIONS (SUMMARY STYLE):
1.  **Summarize Evidence:** Do NOT quote the student directly. Instead, summarize what they did in your own words.
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
* **⚠️ Improvements:** [Summary of errors. Did they compare to specific literature?]

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

# --- UPDATED TEXT EXTRACTION TO INCLUDE TABLES ---
def extract_text_from_docx(file):
    try:
        doc = Document(file)
        full_text = []
        
        # 1. Extract Paragraphs
        for para in doc.paragraphs:
            full_text.append(para.text)
            
        # 2. Extract Tables (Crucial for Variables/Data sections)
        if doc.tables:
            full_text.append("\n--- DETECTED TABLES ---\n")
            for table in doc.tables:
                for row in table.rows:
                    row_text = [cell.text.strip() for cell in row.cells]
                    full_text.append(" | ".join(row_text))
                full_text.append("\n") # Space between tables
        
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

# --- MATH CHECKER ---
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

# --- CSV CLEANER FOR SHEETS ---
def clean_for_sheets(text):
    if not isinstance(text, str): return text
    # Remove headers
    text = re.sub(r'###\s*', '', text)
    # Remove bold markers
    text = text.replace('**', '')
    # Convert bullets
    text = re.sub(r'^\*\s', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^-\s', '• ', text, flags=re.MULTILINE)
    return text.strip()

def grade_submission(file):
    ext = file.name.split('.')[-1].lower()
    
    if ext == 'docx':
        text_content = extract_text_from_docx(file)
        user_message = [
            {
                "type": "text",
                "text": (
                    f"Please grade this lab report based on the Pre-IB rubric below.\n"
                    f"Note: This is a converted Word Document. The text content is provided below, followed by any embedded images.\n\n"
                    f"⚠️ CRITICAL INSTRUCTIONS:\n"
                    f"1. For VARIABLES: Look for tables with 'Independent,' 'Dependent,' 'Control' labels. If found, score 9-10.\n"
                    f"2. For REFERENCES: If 3+ credible sources are present, the score MUST be between 9.0 and 10.0, regardless of formatting.\n\n"
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
                    f"3. Be strict about significant figures, error analysis, and citations.\n"
                    f"4. ⚠️ REFERENCES RULE: If 3+ credible sources are present, MINIMUM score is 9.0.\n"
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
            # Temperature=0 for Maximum Consistency
            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=3500,
                temperature=0.0,
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

# --- WORD FORMATTER (Keep bolding) ---
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
    
    # Prepare DataFrame for Sheets (Clean Text)
    df = pd.DataFrame(st.session_state.current_results)
    
    # Create a copy for CSV export and clean the feedback column
    sheets_df = df[["Filename", "Score", "Feedback"]].copy()
    sheets_df["Feedback"] = sheets_df["Feedback"].apply(clean_for_sheets)
    
    csv_data = sheets_df.to_csv(index=False).encode('utf-8-sig') # utf-8-sig for Excel/Sheets compatibility
    
    master_doc_data = create_master_doc(st.session_state.current_results, st.session_state.current_session_name)
    zip_data = create_zip_bundle(st.session_state.current_results)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📄 Google Docs Compatible (.docx)", master_doc_data, f'{st.session_state.current_session_name}_Docs.docx', "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        st.caption("Upload to Drive -> Open as Google Doc")
    with col2:
        st.download_button("📦 Student Bundle (.zip)", zip_data, f'{st.session_state.current_session_name}_Students.zip', "application/zip", use_container_width=True)
    with col3:
        st.download_button("📊 Google Sheets Compatible (.csv)", csv_data, f'{st.session_state.current_session_name}_Sheets.csv', "text/csv", use_container_width=True)
        st.caption("Import into Google Sheets")

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
            
    # FIXED LOGIC: Only show divider if there is something below it
    if st.session_state.saved_sessions:
        st.divider()
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

    st.divider() # Always separate history from criteria
    
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
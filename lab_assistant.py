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
  * **IMPORTANT:** Do NOT deduct points for superscript/subscript errors in graph titles, axis labels, or data tables. These are technical elements where formatting limitations are common.
  * Consistent use of "I/We": Deduct heavily.
  * NOTE: Do NOT deduct points for minor layout inconsistencies (margins, fonts, spacing, indentation).
- PARTIAL CREDIT: Award partial points if student shows awareness of professional tone but has some lapses.

2. INTRODUCTION (10 pts):
- Criteria: Clear objective, background theory, balanced equations.
- PARTIAL CREDIT: Award points proportionally. For example:
  * Clear objective present: 3-4 pts
  * Background theory included: 3-4 pts
  * Balanced equations present: 2-3 pts

3. HYPOTHESIS (10 pts):
- Criteria: Specific prediction with scientific justification.
- PARTIAL CREDIT: 
  * Prediction stated but lacks specificity: 5-7 pts
  * Scientific justification attempted but weak: award appropriate partial credit

4. VARIABLES (10 pts):
- Criteria: IV (units/range), DV (method), 3+ Controlled Variables.
- **ACCEPTABLE FORMATS:** Students may present variables in paragraph form OR in a data table format. BOTH formats are equally acceptable.
- **TABLE FORMAT GUIDANCE:** If variables are presented in a table with columns like "Variable Type," "Description," "Units," etc., this is FULLY acceptable and should be graded the same as paragraph format.
- **CRITICAL INSTRUCTION:** Carefully examine the ENTIRE document for a variables table - it may appear as a standalone table with headers like "Variable," "Type of Variable," "How it is measured or controlled." This is EXCELLENT work.
- SCORING RULE: If control variables are listed but not explained/justified properly, score exactly 8/10.
- LENIENT GRADING APPROACH:
  * **Focus on identification over perfection**: Students who identify variables correctly should receive most points even if descriptions are brief.
  * **10/10:** IV + DV + 3+ Control Variables with clear explanations/descriptions (table or paragraph format)
  * **9/10:** IV + DV + 3+ Control Variables identified with minimal explanations
  * **8/10:** 3+ Control variables listed but not explained in detail
  * **7/10:** 2 Control variables listed
  * **6/10:** Only IV and DV properly identified
  * **Table with all three variable types clearly identified with descriptions**: 10/10
- PARTIAL CREDIT: Award generously for demonstrating understanding of variable types, even if details are incomplete.

5. PROCEDURES (10 pts):
- Criteria: Numbered steps, specific quantities, safety.
- SCORING RULE: A missing diagram is a MINOR deduction (-0.5 points).
- PARTIAL CREDIT: Award points for procedures that are mostly complete but lack some specificity.

6. RAW DATA (10 pts) [NO UNCERTAINTIES REQUIRED]:
- Criteria: Qualitative observations, clear tables, units, consistent significant figures.
- NOTE: Pre-IB students are NOT required to include uncertainties (±). Do NOT deduct for missing uncertainties.
- CRITICAL: Deduct if significant figures are inconsistent.
- PARTIAL CREDIT: Award points for data tables that are present but have minor formatting issues.

7. DATA ANALYSIS (10 pts) [SIG FIGS CRITICAL]:
- Criteria: Sample calculation shown, graphs (axes/trendlines), R² value.
- SIG FIGS: Students may keep extra digits in intermediate steps. ONLY the final result must be rounded correctly.
- DEDUCTIONS: -0.5 for partial effort, -1.0 for zero attention to sig figs.
- PARTIAL CREDIT: 
  * Calculation shown but incomplete: award partial points
  * Graph present but missing labels or trendline: award partial points

8. CONCLUSION (10 pts):
- Criteria: Statement of support/refutation, specific data evidence.
- CRITICAL REQUIREMENT: Must include specific comparisons to PUBLISHED LITERATURE (theoretical values or accepted standards) to support or contradict the results.
- PARTIAL CREDIT: Award points for conclusions that reference data even if literature comparison is weak or missing.

9. EVALUATION (10 pts) [UPDATED FORMULAIC SCORING]:
- 5 POINTS: Lists at least 4 sources of error (any combination of systematic/random).
- +1 POINT: Specifically identifies which errors are systematic vs. random.
- UP TO +2 POINTS: Explains the impact of these errors on data. (Award 1 pt for weak/partial explanation, 2 pts for thorough explanation).
- UP TO +2 POINTS: Suggests realistic improvements for future experiments. (Award 1 pt for weak/partial suggestions, 2 pts for strong suggestions).
- PARTIAL CREDIT: Award proportional points even if student lists fewer than 4 errors (e.g., 2-3 errors listed = 3-4 points).

10. REFERENCES (10 pts):
- Criteria: Sources listed and cited.
- LENIENT GRADING APPROACH:
  * **Primary focus: Are sources present and cited in the text?** This is 90% of the score.
  * **Secondary consideration: Formatting quality** This is only 10% of the score.
  * If sources are present and cited in text, START at 9/10 minimum.
  * **10/10:** Perfect or near-perfect APA formatting with all sources cited
  * **9.5/10:** Minor APA formatting errors such as inconsistent capitalization, missing italics on one or two sources, or minor punctuation issues (-0.5 pts)
  * **9/10:** Multiple minor errors across several sources OR 1-2 more significant formatting issues (-1.0 pt MAX)
  * **7-8/10:** Sources present but no in-text citations OR only 1-2 sources present
  * **0-3/10:** No references section at all
- **IMPORTANT:** If a student has 10+ sources that are cited throughout the text, they should receive 9.5/10 or 10/10 unless there are MAJOR systematic problems.
- **Examples of minor errors (worth only -0.5 pt TOTAL):**
  * Inconsistent capitalization in titles
  * Missing italics on some journal/website names
  * Minor punctuation inconsistencies
  * Date format variations
  * Slightly incomplete URLs that still function
- CRITICAL: Do NOT deduct more than 1.0 point total for formatting issues as long as sources are present and cited.
- PARTIAL CREDIT: Prioritize the presence of sources over perfect formatting. Students who made an effort to cite sources should receive 9-10 points in most cases.
"""

# --- 4. SYSTEM PROMPT ---
SYSTEM_PROMPT = """You are an expert Pre-IB Chemistry Lab Grader. 
Your goal is to grade student lab reports according to the specific rules below.

### ⚖️ CONSISTENCY & BIAS ELIMINATION PROTOCOL (CRITICAL):
**ABSOLUTE GRADING CONSISTENCY IS MANDATORY**

* **Zero Drift:** You must grade every paper with EXACTLY the same standard. The first paper and the last paper must be held to identical criteria.
* **Blind Grading Mindset:** Grade each report as if it's the only one you'll ever see. Do not adjust standards based on what you've seen in previous reports.
* **No Comparative Grading:** Never grade a report as "better than the last one" or "worse than average." Each report stands alone against the rubric.
* **Eliminate Fatigue Bias:** Maintain the same level of scrutiny and attention to detail for every single report, regardless of how many you've graded.
* **No Name/Order Bias:** The student's name or the order in which reports are graded must never influence the score.
* **Rigid Adherence to Deductions:** Apply the specific point deductions (e.g., -0.5, -1.0) with mathematical precision. If Report #1 loses 0.5 points for a missing graph label, Report #20 must lose exactly 0.5 points for the same issue.
* **Calibration Check:** Before scoring each section, mentally review: "What exact criteria am I looking for? What are the specific point deductions?" This prevents standards from drifting.
* **Partial Credit Philosophy:** Recognize and reward genuine effort. Students learning lab report writing should receive credit for attempts that show understanding, even if execution is incomplete. However, apply this philosophy CONSISTENTLY - similar levels of effort should receive similar partial credit across all reports.
* **Document Your Reasoning:** When deducting points, ensure the reason would apply equally to any student showing the same issue.

**CONSISTENCY SELF-CHECK (Apply to every report):**
- Would I deduct the same points if this were the first report I graded today?
- Am I applying the exact same standard I used for the previous report?
- Is this score based solely on the rubric criteria, not on comparison to other reports?
- Have I avoided any unconscious bias based on writing quality, name, or order?

### 🧠 SCORING ALGORITHMS:

1.  **FORMATTING (Section 1):**
    * **Layout:** Do NOT deduct points for minor layout/formatting inconsistencies. Ignore spacing/margin issues.
    * **Subscripts/Superscripts - BODY TEXT ONLY:** Count errors ONLY in paragraphs and written explanations (Introduction, Conclusion, Evaluation, etc.).
        * **IGNORE errors in:** Graph titles, axis labels, data tables, figure captions.
        * If 0-2 errors in body text: **-0 pts** (Ignore).
        * If >2 errors in body text: **-1.0 pt**.
    * **Rationale:** Graphs and tables often have technical limitations for formatting chemical formulas. Only assess professional writing in body text.
    * **Partial Credit:** If student shows awareness of professional tone but has occasional lapses, award 7-9 points depending on severity.

2.  **INTRODUCTION (Section 2):**
    * **Partial Credit Breakdown:** 
        * Clear objective: 3-4 pts
        * Background theory: 3-4 pts  
        * Balanced equations: 2-3 pts
    * Award points proportionally based on what is present and quality.

3.  **HYPOTHESIS (Section 3):**
    * **Partial Credit:** A hypothesis that lacks specificity or weak justification can still earn 5-7 points if the basic structure is present.

4.  **VARIABLES (Section 4):**
    * **LENIENT APPROACH:** Focus on whether students understand the three variable types, not perfection in descriptions.
    * **ACCEPTABLE FORMATS:** Variables may be presented in paragraph form OR in a table format. Both are equally valid.
        * **Table format example:** A table with columns like "Variable Type," "Variable," "Description," "Units/How Controlled" is FULLY acceptable.
        * **CRITICAL:** Carefully examine the document for tables - they may appear anywhere in the report, not just in a dedicated "Variables" section.
        * Grade table format the same as paragraph format - look for clear identification of IV, DV, and 3+ control variables.
    * **Scoring Guide:**
        * **10/10:** IV + DV + 3+ Control Variables clearly identified with explanations (in ANY format - table or paragraph)
        * **9/10:** IV + DV + 3+ Control Variables identified, minimal explanations
        * **8/10:** IV + DV + 3 Control Variables listed but not explained (FIXED RULE)
        * **7/10:** 2 Control variables listed
        * **6/10:** Only IV and DV identified
    * **Important:** If you find a table with variable types clearly labeled (Independent, Dependent, Control) with descriptions, this is EXCELLENT work and deserves 9-10 points.
    * **Partial Credit:** Be generous. If a student shows they understand what variables are (in any format), they should score 7-10 points.

5.  **PROCEDURES (Section 5):**
    * **Rule:** If the ONLY thing missing is the diagram, the score should be **9.5/10**.
    * **Partial Credit:** Procedures that are mostly complete but lack some specific quantities can earn 7-9 points.

6.  **RAW DATA (Section 6):**
    * **Partial Credit:** Data tables present but with minor issues (formatting, some missing units) can earn 7-9 points.

7.  **DATA ANALYSIS (Section 7) - CALCULATION CHECK:**
    * **Intermediate vs. Final:** Students are allowed to keep extra digits in intermediate steps. ONLY grade the sig figs of the **final answer**.
    * **Deduction Logic:**
        * Mostly right but missed one/two: **-0.5 points**.
        * Completely ignored sig figs: **-1.0 point**.
    * **Partial Credit:** Incomplete calculations or graphs can earn 5-8 points depending on what's present.

8.  **CONCLUSION (Section 8) - LITERATURE CHECK:**
    * **Requirement:** The student MUST compare their result to a published literature value or theory.
    * **Evaluation:** If they simply say "My results matched theory" without citing a specific value or source, this is insufficient.
    * **Partial Credit:** A conclusion that references their own data but lacks literature comparison can earn 6-8 points.

9.  **EVALUATION (Section 9) - UPDATED FORMULA:**
    * Start with **0**.
    * Add **5 points** if they list at least **4 sources of error** (any combination of systematic/random).
    * Add **1 point** if they specifically identify which errors are systematic vs. random.
    * Add **2 points** if they explain the *impact* of errors thoroughly (Award **1 point** if the explanation is vague/weak).
    * Add **2 points** if they explain *improvements* well (Award **1 point** if the suggestion is vague/weak).
    * **Partial Credit for Fewer Errors:** If student lists 2-3 errors, award 3-4 points proportionally.

10.  **REFERENCES (Section 10):**
    * **LENIENT APPROACH:** If sources are present and cited, students should receive 9-10 points in almost all cases.
    * **Scoring Guide:**
        * Sources present + cited in text + perfect/near-perfect formatting = **10/10**
        * Sources present + cited in text + minor APA errors (missing italics, capitalization inconsistencies, punctuation) = **9.5/10** (-0.5 pt)
        * Sources present + cited in text + multiple minor APA errors = **9/10** (MAX -1.0 pt for formatting)
        * Sources present but missing in-text citations = 7-8/10
        * Only 1-2 sources = 7-8/10
        * No references section = 0-3/10
    * **Examples of MINOR errors (deduct only -0.5 pt TOTAL):**
        * Inconsistent capitalization in titles
        * Missing or incorrect italics
        * Minor punctuation issues (commas, periods)
        * Slightly incomplete URLs
        * Date formatting inconsistencies
    * **Examples of issues worth -1.0 pt MAX:**
        * Multiple types of formatting errors combined
        * Several sources with consistent formatting problems
    * **Critical Rule:** Do NOT deduct more than 1 point for APA formatting issues. If 10+ sources are present and cited in text, assume 9.5/10 or 10/10 unless there are MAJOR problems.
    * **Focus:** 90% of the score should be based on whether sources exist and are cited, only 10% on formatting perfection.

### 📝 FEEDBACK INSTRUCTIONS (SUMMARY STYLE):
1.  **Summarize Evidence:** Do NOT quote the student directly. Instead, summarize what they did in your own words.
2.  **Structure:** "✅ Strengths" and "⚠️ Improvements" for every section.
3.  **Acknowledge Effort:** When awarding partial credit, mention what the student did well and what needs improvement.

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
* **✅ Strengths:** [Summary of good work - note how many errors listed, if systematic/random identified]
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
                    f"3. Be strict about significant figures, error analysis, and citations.\n"
                    f"4. Award partial credit when students make genuine attempts to follow the rubric."
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
import streamlit as st
import anthropic
import base64
import pandas as pd
import os
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

# --- 3. HARDCODED RUBRIC ---
PRE_IB_RUBRIC = """TOTAL: 100 POINTS (10 pts per section)

GENERAL PRINCIPLE: Award partial credit when students make genuine attempts to follow the rubric. Recognize effort.

1. FORMATTING (10 pts):
- Criteria: Third-person passive voice, professional tone, superscripts/subscripts used correctly IN THE BODY TEXT.
- DEDUCTIONS (TIERED): 
  * **SUPERSCRIPT/SUBSCRIPT ERRORS:** Count errors in paragraphs/body text (Ignore graphs/tables).
    * **1 or 2 errors:** **-0.5 Points** (resulting score: 9.5).
    * **3 or more errors:** **-1.0 Point** (resulting score: 9.0).
  * Consistent use of "I/We": Deduct heavily.
  * NOTE: Do NOT deduct points for minor layout inconsistencies (margins, fonts, spacing).

2. INTRODUCTION (10 pts):
- Criteria: Clear objective, background theory, balanced equations.
- **OBJECTIVE:** Specific lab objectives must be explicitly stated.
  * **Penalty:** If missing or unclear, **-1.0 point**.
- PARTIAL CREDIT: Award points proportionally.

3. HYPOTHESIS (10 pts):
- Criteria: Specific prediction with scientific justification.

4. VARIABLES (10 pts):
- Criteria: IV (units/range), DV (method), 3+ Controlled Variables.
- **SCORING TIERS:**
  * **10/10:** IV + DV + 3+ Control Variables with explanations.
  * **9.5/10:** Variables listed, but description of **how to measure DV** is vague. (Deduct 0.5).
  * **9.0/10:** Variables listed, but explanations missing for multiple variables. (Deduct 1.0).

5. PROCEDURES (10 pts):
- Criteria: Numbered steps, specific quantities, safety.
- SCORING RULE: A missing diagram is a MINOR deduction (-0.5 points).

6. RAW DATA (10 pts):
- Criteria: Qualitative observations, clear tables, units, consistent significant figures.
- FORMATTING: Do NOT deduct for table aesthetics. Focus on data clarity.

7. DATA ANALYSIS (10 pts) [GRAPH & CALCULATION CRITICAL]:
- Criteria: Sample calculation shown, graphs (axes/trendlines), R² value.
- **UNCERTAINTY ANALYSIS:** NOT REQUIRED. Do NOT deduct for missing error bars/propagation.
- **INTERMEDIATE PRECISION:** Excessive precision (extra digits) in intermediate steps is ALLOWED. Only penalize significant figures in the **FINAL RESULT**.
- **MANDATORY GRAPH CHECKLIST:**
  * **Format:** Must be a Scatterplot with a Trendline.
  * **Labels:** Axis labels with Units MUST be present.
  * **Stats:** R² value AND Trendline Equation MUST be listed on the graph.
  * **Logic:** Trendline type must be appropriate (e.g., don't force linear fit on curved data).
- DEDUCTION: -0.5 for partial effort, -1.0 for zero attention.

8. CONCLUSION (10 pts) [STRICT DEDUCTIONS]:
- **IV/DV RELATIONSHIP:** Must explain the specific relationship (trend) shown by the graph.
  * **ACCEPTED TERMINOLOGY:** "Proportional" is accepted for positive trends. "Inverse" is accepted for negative trends.
  * **Penalty:** If not explained thoroughly, **-1.0 point**.
- **THEORY CONNECTION:** Must connect results to Chemical Theory.
  * **Penalty:** If missing, **-1.0 point**.
- **QUANTITATIVE SUPPORT:** Must support conclusion with specific numbers.
  * **Penalty:** If missing, **-2.0 points**.
- **QUALITATIVE SUPPORT:** Must support conclusion with observations.
  * **Penalty:** If missing, **-0.5 points**.
- **STATISTICS (R vs R²):**
  * **R (Correlation Coefficient):** Must explain strength and DIRECTION. **Penalty:** If missing, **-1.0 point**.
  * **R² (Coefficient of Determination):** Must explain fit/variability. **Penalty:** If explained poorly, **-0.5 points**.
  * **NOTE:** If R is missing but R² is explained well, DO NOT deduct for R². Total stats deduction should be -1.0.

9. EVALUATION (10 pts) [STRICT QUALITY GATES]:
- **BASE SCORE:** Start at 0. Add points ONLY if specific criteria are met.
- **5 POINTS:** Lists at least 4 distinct sources of error.
- **+1 POINT:** Correctly identifies Systematic vs. Random errors.
- **+2 POINTS (IMPACT):**
  * **2 Points:** Specific directional impact ("caused mass to increase") described for **100% of listed errors**.
  * **1 Point (Partial Deduction):** Directional impact described for **SOME** errors, or if even ONE is missing/vague. (Deduct 1.0).
  * **0 Points (Full Deduction):** No directional impact described for ANY error. (Deduct 2.0).
- **+2 POINTS (IMPROVEMENT):** Must suggest **SPECIFIC** equipment or procedural changes.
  * **2 Points:** Specific improvements for all errors.
  * **1.5 Points (Deduct 0.5):** Improvements listed but slightly vague (e.g. "use more precise equipment" without naming it).
  * **0 Points (Full Deduction):** No improvements or completely generic ("be more careful").

10. REFERENCES (10 pts):
- Criteria: Sources listed and cited.
- **ABSOLUTE SCORING LOGIC (The "9-Point Floor"):**
  * **If 3+ credible sources found:** Score **MUST** be 9.0, 9.5, or 10.0.
"""

# --- 4. SYSTEM PROMPT ---
SYSTEM_PROMPT = """You are an expert Pre-IB Chemistry Lab Grader. 
Your goal is to grade student lab reports according to the specific rules below.

### 🧠 SCORING ALGORITHMS (STRICT ENFORCEMENT):

1.  **MATH ENFORCEMENT (CRITICAL):**
    * **Decimal Scores are MANDATORY.**
    * If you deduct 0.5 points, the score is **9.5**. 
    * **DO NOT** round 9.5 down to 9.0.

2.  **VARIABLES (Section 4) - VAGUENESS CHECK:**
    * Check the **Dependent Variable (DV)** description.
    * If the method of measurement is **vague** (e.g., "we measured time" instead of "we used a stopwatch to measure time until color change"), **Deduct 0.5 points** (Score 9.5).
    * Do NOT deduct 1.0 point unless multiple variables are undefined.

3.  **CONCLUSION (Section 8) - STATISTICAL & TERMINOLOGY INTELLIGENCE:**
    * **IV/DV Trend:** * **ALLOW SYNONYMS:** "Proportional" = Positive Relationship. "Inverse" = Negative Relationship. 
      * **Do NOT deduct** if these terms are used.
    * **R² Check:** Look for keywords: "fit," "variability," "scatter," "trendline." If present, give credit for R² explanation.
    * **R Check:** Look for keywords: "correlation," "strength," "positive/negative."
    * **Scoring:**
      * Missing R only = -1.0 point.
      * Missing R AND R² explanation = -1.5 points.
      * **Do not penalize R² explanation if it is correct, even if R is missing.**

4.  **EVALUATION (Section 9) - STRICT IMPACT & IMPROVEMENT AUDIT:**
    * **IMPACT (2 pts):**
      * Impact explained for **100%** of errors? -> **+2 Points.**
      * Impact explained for **SOME** errors (even if only 1 is missing)? -> **+1 Point (Deduct 1.0).**
      * Impact explained for **NONE**? -> **+0 Points (Deduct 2.0).**
    * **IMPROVEMENTS (2 pts):**
      * Specific equipment/method named? -> **+2 Points.**
      * Vague suggestions ("use better tools")? -> **+1.5 Points (Deduct 0.5).**
      * No suggestions/Generic ("be careful")? -> **+0 Points (Deduct 2.0).**

### 📝 FEEDBACK STYLE (EXPANDED & HUMAN-LIKE):
* **AVOID ROBOTIC CHECKLISTS:** Do not use "[Yes/No]" in your final output. 
* **USE NATURAL LANGUAGE:** Instead of "R² present: No", write "The conclusion discusses the data trends but fails to mention the R² value or its implications."
* **EXPLAIN WHY:** Write 2-3 sentences for each section.

### OUTPUT FORMAT:
Please strictly use the following format. Do not use horizontal rules (---) between sections.

# 📝 SCORE: [Total Points]/100
STUDENT: [Filename]

**📊 OVERALL SUMMARY & VISUAL ANALYSIS:**
* [1-2 sentences on quality]
* [Critique of graphs/images]

**📝 DETAILED RUBRIC BREAKDOWN:**

**1. FORMATTING: [Score]/10**
* **✅ Strengths:** [Detailed explanation of tone/voice quality]
* **⚠️ Improvements:** [**MANDATORY:** "Found [X] subscript errors." (If X=1 or 2, Score **MUST** be 9.5. If X>=3, Score is 9.0 or lower).]

**2. INTRODUCTION: [Score]/10**
* **✅ Strengths:** [Detailed explanation of objective/theory coverage]
* **⚠️ Improvements:** [**OBJECTIVE CHECK:** "Objective explicit? [Yes/No]" (-1 pt if No). Also explain missing equations/theory.]

**3. HYPOTHESIS: [Score]/10**
* **✅ Strengths:** [Quote prediction and praise the scientific reasoning]
* **⚠️ Improvements:** [Explain specifically where the justification falls short]

**4. VARIABLES: [Score]/10**
* **✅ Strengths:** [**LIST:** "Identified IV: [X], DV: [Y], Controls: [A, B, C]" and comment on clarity.]
* **⚠️ Improvements:** [If DV measurement is vague, state: "The method for measuring the DV was vague (-0.5 pts)." Suggest specific improvement.]

**5. PROCEDURES: [Score]/10**
* **✅ Strengths:** [Comment on reproducibility and safety details]
* **⚠️ Improvements:** [Identify exactly which step is vague and how to fix it]

**6. RAW DATA: [Score]/10**
* **✅ Strengths:** [Comment on data organization and unit clarity]
* **⚠️ Improvements:** [Quote values with wrong units/sig figs and explain the correct format]

**7. DATA ANALYSIS: [Score]/10**
* **✅ Strengths:** [Summarize the calculation process. If Graph is perfect, mention that the scatterplot, equation, and labels are all correct here.]
* **⚠️ Improvements:** [**GRAPH AUDIT:** Write a natural summary of what is missing. Example: "The graph includes a trendline but is missing the equation and R² value. Additionally, the y-axis lacks units."]

**8. CONCLUSION: [Score]/10**
* **✅ Strengths:** [Quote data used to support the claim]
* **⚠️ Improvements:** [**CRITICAL CHECKS:** Summarize missing elements naturally. Ensure you comment on:
  1. IV/DV Relationship (-1) **(Note: "Proportional" and "Inverse" are ACCEPTED)**
  2. Chemical Theory (-1)
  3. Quantitative Support (-2)
  4. Qualitative Support (-0.5)
  5. **R and R² Explanation** (-1.0 if R missing, -0.5 if R² explained poorly)]

**9. EVALUATION: [Score]/10**
* **✅ Strengths:** [**LIST:** "You identified: [Error 1], [Error 2]..." and comment on depth.]
* **⚠️ Improvements:** [**IMPACT/IMPROVEMENT AUDIT:** * "You listed [X] errors but only provided specific directional impacts for [Y] of them. (-1 pt)"
  * "Improvements were listed but were slightly vague (e.g., did not name specific equipment). (-0.5 pt)" ]

**10. REFERENCES: [Score]/10**
* **✅ Strengths:** [**MANDATORY:** "Counted [X] credible sources." Comment on quality.]
* **⚠️ Improvements:** [Specific formatting error explanation]

**💡 TOP 3 ACTIONABLE STEPS FOR NEXT TIME:**
1. [Step 1 - Specific]
2. [Step 2 - Specific]
3. [Step 3 - Specific]
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

# --- UPDATED TEXT EXTRACTION (WITH POINTER RESET) ---
def extract_text_from_docx(file):
    try:
        file.seek(0) # CRITICAL FIX: Reset pointer before reading
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
        file.seek(0) # CRITICAL FIX: Reset pointer before reading
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
            # UPDATED REGEX FOR HEADER SCORE
            text = re.sub(r"#\s*📝\s*SCORE:\s*[\d\.]+/100", f"# 📝 SCORE: {total_score}/100", text, count=1)
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

def grade_submission(file, model_id):
    ext = file.name.split('.')[-1].lower()
    
    if ext == 'docx':
        text_content = extract_text_from_docx(file)
        
        # Check for empty text to warn user
        if len(text_content.strip()) < 50:
            text_content += "\n\n[SYSTEM NOTE: Very little text text extracted. Content may be in images or text boxes.]"
            
        # Use String Concatenation instead of f-string to prevent brace errors
        prompt_text = (
            "Please grade this lab report based on the Pre-IB rubric below.\n"
            "Note: This is a converted Word Document. The text content is provided below, followed by any embedded images.\n\n"
            "⚠️ CRITICAL INSTRUCTIONS:\n"
            "1. **BE SPECIFIC & EXPANDED:** Write 2-3 sentences per section explaining the score. Quote text/data. No generic feedback.\n"
            "2. **VARIABLES:** List the exact variables found. If found, score 9-10.\n"
            "3. **REFERENCES:** Count the sources. If >= 3, MINIMUM score is 9.0.\n"
            "4. **FORMATTING MATH:** 1-2 errors = -0.5 pts (Score 9.5). 3+ errors = -1.0 pt (Score 9.0).\n"
            "5. **GRAPHS:** Check for R², Equation, Scatterplot format, and Units. Place audit in Strengths if perfect.\n"
            "6. **CONCLUSION:** Check for IV/DV trend (-1), Theory (-1), Quant Data (-2), Qual Data (-0.5), R Value (-1.0), R² (-0.5).\n"
            "7. **DATA ANALYSIS:** Do NOT penalize for missing uncertainty analysis. Ignore excessive precision in intermediate steps.\n"
            "8. **EVALUATION:** Penalize vague impact/improvements. Must specify DIRECTION of error and SPECIFIC equipment for **ALL** errors. (0 pts if missing, 1 pt if partial).\n\n"
            "--- RUBRIC START ---\n" + PRE_IB_RUBRIC + "\n--- RUBRIC END ---\n\n"
            "STUDENT TEXT:\n" + text_content
        )
        
        user_message = [
            {
                "type": "text",
                "text": prompt_text
            }
        ]
        images = extract_images_from_docx(file)
        if images:
            user_message.extend(images)
    else:
        base64_data = encode_file(file)
        if not base64_data: return "Error processing file."
        media_type = get_media_type(file.name)
        
        prompt_text = (
            "Please grade this lab report based on the Pre-IB rubric below.\n\n"
            "--- RUBRIC START ---\n" + PRE_IB_RUBRIC + "\n--- RUBRIC END ---\n\n"
            "INSTRUCTIONS:\n"
            "1. **BE SPECIFIC & EXPANDED:** Write 2-3 sentences per section explaining the score. Quote text/data. No generic feedback.\n"
            "2. **VARIABLES:** List the exact variables found. If found, score 9-10.\n"
            "3. **REFERENCES:** Count the sources. If >= 3, MINIMUM score is 9.0.\n"
            "4. **FORMATTING MATH:** 1-2 errors = -0.5 pts (Score 9.5). 3+ errors = -1.0 pt (Score 9.0).\n"
            "5. **GRAPHS:** Check for R², Equation, Scatterplot format, and Units. Place audit in Strengths if perfect.\n"
            "6. **CONCLUSION:** Check for IV/DV trend (-1), Theory (-1), Quant Data (-2), Qual Data (-0.5), R Value (-1.0), R² (-0.5).\n"
            "7. **DATA ANALYSIS:** Do NOT penalize for missing uncertainty analysis. Ignore excessive precision in intermediate steps.\n"
            "8. **EVALUATION:** Penalize vague impact/improvements. Must specify DIRECTION of error and SPECIFIC equipment for **ALL** errors. (0 pts if missing, 1 pt if partial).\n"
        )
        
        user_message = [
            {
                "type": "text",
                "text": prompt_text
            },
            {
                "type": "document" if media_type == 'application/pdf' else "image",
                "source": {"type": "base64", "media_type": media_type, "data": base64_data}
            }
        ]

    # --- UPDATED RETRY LOGIC FOR 529 OVERLOAD ERRORS ---
    max_retries = 5 
    retry_delay = 5 
    
    for attempt in range(max_retries):
        try:
            # Temperature=0 for Maximum Consistency
            response = client.messages.create(
                model=model_id, # Uses the ID passed from Sidebar
                max_tokens=3500,
                temperature=0.0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}]
            )
            raw_text = response.content[0].text
            corrected_text = recalculate_total_score(raw_text)
            return corrected_text
            
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            # Check for Overloaded (529) or Rate Limit (429)
            if isinstance(e, anthropic.APIStatusError) and e.status_code == 529:
                status_msg = f"⚠️ Server Overloaded (529). Retrying attempt {attempt+1}/{max_retries}..."
                print(status_msg) # Log to console
                time.sleep(retry_delay * (attempt + 1)) # Exponential backoff
                continue
            
            if isinstance(e, anthropic.RateLimitError):
                status_msg = f"⚠️ Rate Limit Hit. Retrying attempt {attempt+1}/{max_retries}..."
                print(status_msg)
                time.sleep(retry_delay * (attempt + 1))
                continue
                
            return f"⚠️ Error: {str(e)}"
            
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

# --- WORD FORMATTER (Strict Symbol Cleaning) ---
def write_markdown_to_docx(doc, text):
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue # SKIP EMPTY LINES (Previous fix maintained)
        
        # 1. Handle H1 Title (# ) - CLEANED
        if line.startswith('# '): 
            clean = line.replace('# ', '').replace('*', '').strip()
            doc.add_heading(clean, level=0)
            continue
        
        # 2. Handle H3 (### ) - CLEANED
        if line.startswith('### '):
            clean = line.replace('### ', '').replace('*', '').strip()
            doc.add_heading(clean, level=3)
            continue
        
        # 3. Handle H2 (## ) - CLEANED
        if line.startswith('## '): 
            clean = line.replace('## ', '').replace('*', '').strip()
            doc.add_heading(clean, level=2)
            continue

        # 4. Handle Bullets (* or -) - CLEANED
        if line.startswith('* ') or line.startswith('- '):
            p = doc.add_paragraph(style='List Bullet')
            content = line[2:] 
        else:
            p = doc.add_paragraph()
            content = line

        # 5. Handle Bold (**text**) - CLEANED
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                clean_text = part[2:-2].replace('*', '') # Strip any lingering asterisks
                run = p.add_run(clean_text)
                run.bold = True
            else:
                p.add_run(part.replace('*', '')) # Strip lingering asterisks

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
    st.header("⚙️ Configuration")
    
    # NEW: Model ID Input to prevent 404 errors with newer models
    user_model_id = st.text_input(
        "🤖 Model ID", 
        value="claude-3-5-sonnet-20241022", 
        help="Change this if you have a specific Beta model or newer ID (e.g. Sonnet 4.5)"
    )
    
    st.divider()
    st.header("💾 History Manager")
    save_name = st.text_input("Session Name", placeholder="e.g. Period 3 - Kinetics")
    if st.button("💾 Save Session"):
        if st.session_state.current_results:
            st.session_state.saved_sessions[save_name] = st.session_state.current_results
            st.success(f"Saved '{save_name}'!")
        else:
            st.warning("No results to save yet.")
            
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

    st.divider() 
    
    with st.expander("View Grading Criteria"):
        st.text(PRE_IB_RUBRIC)

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
        
        # POLITE DELAY to avoid 529s on loop
        time.sleep(2) 

        feedback = grade_submission(file, user_model_id) # PASSING USER MODEL ID
        score = parse_score(feedback)
        
        new_results.append({
            "Filename": file.name,
            "Score": score,
            "Feedback": feedback
        })
        progress.progress((i + 1) / len(processed_files))
        

    st.session_state.current_results = new_results
    status.success("✅ Grading Complete! Scrolling down...")
    progress.empty()

# --- 8. PERSISTENT DISPLAY ---
if st.session_state.current_results:
     display_results_ui()
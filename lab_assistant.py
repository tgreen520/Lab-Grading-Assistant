import streamlit as st
import anthropic
import base64
import pandas as pd
import os
import json
import zipfile
import time
from docx import Document
from io import BytesIO

# --- 1. CONFIGURATION ---

# Check for Key in Secrets (Streamlit Cloud) OR Environment (Local PC)
if "ANTHROPIC_API_KEY" in st.secrets:
    API_KEY = st.secrets["ANTHROPIC_API_KEY"]
elif "ANTHROPIC_API_KEY" in os.environ:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
else:
    st.error("🚨 API Key not found!")
    st.info("On Streamlit Cloud, add your key to the 'Secrets' settings.")
    st.stop()

# Model Selection
MODEL_NAME = "claude-sonnet-4-20250514"

# --- 2. HARDCODED RUBRIC (PRE-IB CHEMISTRY) ---
PRE_IB_RUBRIC = """TOTAL: 100 POINTS (10 pts per section)

1. FORMATTING (10 pts):
- Exemplary (9-10): All sections present. Third-person passive voice used consistently. Professional tone. Clear headings.
- Needs Improvement: Missing sections. Use of "I/We". Informal tone.

2. INTRODUCTION (10 pts):
- Exemplary (9-10): Clear objective ("to determine..."). Relevant chemical theories explained in detail. Balanced equations with state symbols included.
- Needs Improvement: Vague objective. Missing background theory or equations.

3. HYPOTHESIS (10 pts):
- Exemplary (9-10): Specific, testable prediction with direction (e.g., "rate will double"). Scientific justification based on theory.
- Needs Improvement: Vague "something will happen". No reasoning provided.

4. VARIABLES (10 pts):
- Exemplary (9-10): Independent Variable (IV) with range/units. Dependent Variable (DV) with measurement method. 3+ Control Variables explained (how & why).
- Needs Improvement: Missing units. Controls listed but not explained. Confusion between IV/DV.

5. PROCEDURES (10 pts):
- Exemplary (9-10): Materials list includes concentrations/sizes. Numbered steps allowing replication. Safety concerns (PPE/Disposal) addressed. Setup diagram included.
- Needs Improvement: Recipe style. Missing safety. Missing quantities.

6. RAW DATA (10 pts):
- Exemplary (9-10): Qualitative observations included (colors, smells). Tables have borders, titles, units, and consistent significant figures.
- Needs Improvement: No qualitative data. Missing units. Inconsistent decimals.

7. DATA ANALYSIS (10 pts):
- Exemplary (9-10): One sample calculation shown fully. Graphs have titles, labeled axes (with units), Trendline/Curve, and R² value.
- Needs Improvement: Missing calculations. Poor graph choice. Missing axis labels.

8. CONCLUSION (10 pts):
- Exemplary (9-10): States if hypothesis is supported/refuted. Cites specific data as evidence. Compares to literature values (% error).
- Needs Improvement: Vague conclusion without data. No comparison to theory.

9. EVALUATION (10 pts):
- Exemplary (9-10): Identifies specific strengths/weaknesses. Distinguishes Random vs. Systematic error. Suggests realistic improvements.
- Needs Improvement: Vague "human error". No distinction of error types. Unrealistic improvements.

10. REFERENCES (10 pts):
- Exemplary (9-10): APA 7th edition format. In-text citations match reference list. Reliable sources (.edu/.gov).
- Needs Improvement: No citations. URL only. Wikipedia used.
"""

# --- 3. SYSTEM PROMPT ---
SYSTEM_PROMPT = """You are an expert Pre-IB Chemistry Lab Grader. 
Your goal is to grade student lab reports strictly according to the provided IB-style rubric.

When analyzing a file, you must perform a "Scientific Deep Dive" before assigning a score.

### Your Analysis Protocols:
1. **Graph & Figure Auditing:**
   - Check if axes are labeled with units and uncertainties (if applicable).
   - Check if trendlines and R² values are present.
   - **Crucial:** Look at the data points. Do they actually support the student's conclusion?

2. **Data & Calculation Check:**
   - Verify significant figures are consistent with equipment precision.
   - Verify 1-2 visible calculations (e.g., slope, percent error).
   - Check for distinction between random and systematic errors.

3. **Grading:**
   - Apply the rubric strictly. Deduct points for missing elements like safety concerns, qualitative observations, or APA citations.

### Output Format:
Please strictly use the following format for your response:

SCORE: [Points Earned]/100
STUDENT: [Name or Filename]
---
**📊 DATA & VISUAL ANALYSIS:**
* [Specific critique of graphs: Title, Axes, Units, Linearity]
* [Verification of calculations: Correct/Incorrect]
* [Comment on data trends]

**📝 RUBRIC BREAKDOWN:**
* **Formatting:** [Score]/10 - [Brief feedback]
* **Introduction:** [Score]/10 - [Brief feedback]
* **Hypothesis:** [Score]/10 - [Brief feedback]
* **Variables:** [Score]/10 - [Brief feedback]
* **Procedures:** [Score]/10 - [Brief feedback]
* **Raw Data:** [Score]/10 - [Brief feedback]
* **Analysis:** [Score]/10 - [Brief feedback]
* **Conclusion:** [Score]/10 - [Brief feedback]
* **Evaluation:** [Score]/10 - [Brief feedback]
* **References:** [Score]/10 - [Brief feedback]

**💡 TOP 3 AREAS FOR IMPROVEMENT:**
1. [Actionable tip]
2. [Actionable tip]
3. [Actionable tip]
"""

# --- 4. PAGE SETUP & STATE ---
st.set_page_config(
    page_title="Pre-IB Lab Grader", 
    page_icon="🧪", 
    layout="wide"
)

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

def process_uploaded_files(uploaded_files):
    """
    Smart Processor:
    1. Handles ZIP files (unzips them).
    2. Handles standard files.
    3. FILTERS OUT junk system files (.DS_Store, desktop.ini) from 'Select All' uploads.
    """
    final_files = []
    
    # Files to ignore
    IGNORED_FILES = {'.ds_store', 'desktop.ini', 'thumbs.db', '__macosx'}
    VALID_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    for file in uploaded_files:
        file_name_lower = file.name.lower()
        
        # Skip junk files immediately
        if file_name_lower in IGNORED_FILES or file_name_lower.startswith('._'):
            continue

        # Check if it is a ZIP file
        if file_name_lower.endswith('.zip'):
            try:
                with zipfile.ZipFile(file) as z:
                    for filename in z.namelist():
                        # Filter junk inside ZIP
                        clean_name = filename.lower()
                        if any(x in clean_name for x in IGNORED_FILES) or filename.startswith('.'):
                            continue
                            
                        # Check extension
                        ext = clean_name.split('.')[-1]
                        if ext in VALID_EXTENSIONS:
                            file_bytes = z.read(filename)
                            virtual_file = BytesIO(file_bytes)
                            virtual_file.name = os.path.basename(filename)
                            final_files.append(virtual_file)
            except Exception as e:
                st.error(f"Error unzipping {file.name}: {e}")
                
        else:
            # It's a regular file - check extension
            ext = file_name_lower.split('.')[-1]
            if ext in VALID_EXTENSIONS:
                final_files.append(file)
            
    return final_files

def grade_submission(file):
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

    # --- RATE LIMIT HANDLING ---
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
            return response.content[0].text
            
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                sleep_time = retry_delay * (attempt + 1)
                time.sleep(sleep_time)
                continue
            else:
                return "⚠️ Error: Rate limit exceeded. Try grading fewer files at once."
                
        except anthropic.APIError as e:
             return f"⚠️ API Error: {str(e)}"
        except Exception as e:
            return f"⚠️ Unexpected Error: {str(e)}"

def parse_score(text):
    try:
        lines = text.split('\n')
        for line in lines:
            if "SCORE:" in line:
                return line.split("SCORE:")[1].strip()
    except:
        pass
    return "N/A"

def create_master_doc(results, session_name):
    doc = Document()
    doc.add_heading(f"Lab Report Grades: {session_name}", 0)
    for item in results:
        doc.add_heading(item['Filename'], level=1)
        doc.add_heading(f"Score: {item['Score']}", level=2)
        doc.add_paragraph(item['Feedback'])
        doc.add_page_break()
    bio = BytesIO()
    doc.save(bio)
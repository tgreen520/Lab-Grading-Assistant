import streamlit as st
import anthropic
import base64
import pandas as pd
import os
import json
import zipfile
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
    """Handles ZIPs and raw files."""
    final_files = []
    for file in uploaded_files:
        if file.name.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(file) as z:
                    for filename in z.namelist():
                        if filename.startswith('__MACOSX') or filename.startswith('.'): continue
                        ext = filename.split('.')[-1].lower()
                        if ext in ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp']:
                            file_bytes = z.read(filename)
                            virtual_file = BytesIO(file_bytes)
                            virtual_file.name = os.path.basename(filename)
                            final_files.append(virtual_file)
            except Exception as e:
                st.error(f"Error unzipping {file.name}: {e}")
        else:
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

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=3500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )
        return response.content[0].text
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

def create_master_doc(results, session_name):
    """Generates ONE .docx file with ALL reports."""
    doc = Document()
    doc.add_heading(f"Lab Report Grades: {session_name}", 0)
    for item in results:
        doc.add_heading(item['Filename'], level=1)
        doc.add_heading(f"Score: {item['Score']}", level=2)
        doc.add_paragraph(item['Feedback'])
        doc.add_page_break()
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()

def create_zip_bundle(results):
    """Generates a ZIP file containing INDIVIDUAL .docx files for each student."""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for item in results:
            # Create individual doc
            doc = Document()
            doc.add_heading(f"Feedback: {item['Filename']}", 0)
            doc.add_heading(f"Score: {item['Score']}", level=1)
            doc.add_paragraph(item['Feedback'])
            
            # Save doc to bytes
            doc_buffer = BytesIO()
            doc.save(doc_buffer)
            
            # Write bytes to zip
            # Clean filename to avoid issues
            safe_name = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
            z.writestr(safe_name, doc_buffer.getvalue())
            
    return zip_buffer.getvalue()

# --- 6. SIDEBAR (HISTORY & SETTINGS) ---
with st.sidebar:
    st.header("💾 History Manager")
    
    # Save Current Session
    st.caption("Save your current grading batch:")
    save_name = st.text_input("Session Name", placeholder="e.g. Period 3 - Kinetics")
    
    if st.button("💾 Save Session"):
        if st.session_state.current_results:
            st.session_state.saved_sessions[save_name] = st.session_state.current_results
            st.success(f"Saved '{save_name}'!")
        else:
            st.warning("No results to save yet.")
            
    st.divider()
    
    # Load Previous Session
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
    else:
        st.caption("No saved sessions found.")

    st.divider()
    
    with st.expander("View Grading Criteria"):
        st.text(PRE_IB_RUBRIC)
    st.caption(f"🤖 Model: {MODEL_NAME}")

# --- 7. MAIN INTERFACE ---
st.title("🧪 Pre-IB Lab Grader")
st.caption(f"Current Session: **{st.session_state.current_session_name}**")

# File Uploader
raw_files = st.file_uploader(
    "📂 Upload Reports (PDF, Images, or ZIP)", 
    type=['pdf', 'png', 'jpg', 'jpeg', 'zip'], 
    accept_multiple_files=True
)

processed_files = []
if raw_files:
    processed_files = process_uploaded_files(raw_files)
    if len(processed_files) > 0:
        st.info(f"Ready to grade **{len(processed_files)}** report(s).")

# Grading Action
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

    st.session_state.current_results = new_results
    status.success("✅ Grading Complete! Don't forget to save this session in the sidebar.")
    progress.empty()

# --- 8. RESULTS DISPLAY ---
if st.session_state.current_results:
    st.divider()
    
    # Prepare exports
    df = pd.DataFrame(st.session_state.current_results)
    csv_data = df.to_csv(index=False).encode('utf-8')
    master_doc_data = create_master_doc(st.session_state.current_results, st.session_state.current_session_name)
    zip_data = create_zip_bundle(st.session_state.current_results)
    
    st.subheader("📤 Batch Export")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.download_button(
            label="📄 Master Doc (All-in-One)",
            data=master_doc_data,
            file_name=f'{st.session_state.current_session_name}_Master.docx',
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )
        st.caption("One file containing all reports.")

    with col2:
        st.download_button(
            label="📦 Student Bundle (.zip)",
            data=zip_data,
            file_name=f'{st.session_state.current_session_name}_Students.zip',
            mime="application/zip",
            use_container_width=True
        )
        st.caption("Separate files for each student.")

    with col3:
        st.download_button(
            label="📊 Gradebook (.csv)", 
            data=csv_data, 
            file_name=f'{st.session_state.current_session_name}_Grades.csv', 
            mime='text/csv',
            use_container_width=True
        )
        st.caption("Spreadsheet of scores.")

    st.divider()
    
    # Display Tabs
    tab1, tab2 = st.tabs(["📊 Gradebook View", "📝 Detailed Feedback"])

    with tab1:
        st.dataframe(df[["Filename", "Score"]], use_container_width=True)

    with tab2:
        for item in st.session_state.current_results:
            with st.expander(f"📄 {item['Filename']} (Score: {item['Score']})"):
                st.markdown(item['Feedback'])
else:
    st.info("Upload files to begin.")
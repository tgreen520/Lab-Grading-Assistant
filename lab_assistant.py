import streamlit as st
import anthropic
import base64
import pandas as pd
import time
from io import BytesIO

# --- 1. CONFIGURATION ---
# This script relies on Streamlit secrets for security.
# Ensure your .streamlit/secrets.toml file contains: ANTHROPIC_API_KEY = "sk-..."
import streamlit as st
import anthropic
import base64
import pandas as pd
import time
from io import BytesIO
import os  # <--- New import needed to read system variables

# --- 1. CONFIGURATION ---

# Try to get the key from the computer's environment variables
API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Check if the key was found. If not, stop the app and warn the user.
if not API_KEY:
    st.error("🚨 API Key not found!")
    st.markdown("""
    To fix this:
    1. Set an Environment Variable named `ANTHROPIC_API_KEY` on your computer.
    2. Restart your terminal/editor.
    """)
    st.stop()

# Model Selection
MODEL_NAME = "claude-sonnet-4-20250514"

# Model Selection: Claude Sonnet 4.5 (as requested)
MODEL_NAME = "claude-sonnet-4-20250514"

# --- SYSTEM PROMPT: THE BRAIN OF THE ASSISTANT ---
SYSTEM_PROMPT = """You are an expert Scientific Lab Grading Assistant. 
Your goal is to grade student lab reports (images or PDFs) with a focus on data integrity, graphical representation, and scientific reasoning.

When analyzing a file, you must perform a "Scientific Deep Dive" before assigning a score.

### Your Analysis Protocols:
1. **Graph & Figure Auditing:**
   - Check if axes are labeled with correct units.
   - Verify if the scale is appropriate (not squashed or misleading).
   - Check if trendlines/curves of best fit are applied correctly.
   - Identify if error bars are present (if applicable).
   - **Crucial:** Look at the data points. Do they actually support the student's conclusion?

2. **Data & Calculation Check:**
   - Check for significant figure usage in tables and calculations.
   - Verify 1-2 visible calculations (e.g., slope of a line, molarity) to ensure accuracy.
   - Identify any outliers the student may have ignored without explanation.

3. **Grading:**
   - Apply the user-provided rubric strictly.
   - If the student's conclusion contradicts their own data, deduct points heavily.

### Output Format:
Please strictly use the following format for your response:

SCORE: [Points Earned]/[Total Points]
STUDENT: [Name or Filename]
---
**📊 DATA & VISUAL ANALYSIS:**
* [Specific critique of graphs: Title, Axes, Units, Linearity]
* [Verification of calculations: Correct/Incorrect]
* [Comment on data trends: Did the student interpret them correctly?]

**📝 RUBRIC FEEDBACK:**
* [Bullet points explaining the score based on the specific rubric criteria]

**💡 AREAS FOR IMPROVEMENT:**
* [1-2 actionable tips for the next lab (e.g., "Always include units on the x-axis", "Your R² value suggests a non-linear relationship")]
"""

# --- 2. PAGE SETUP ---
st.set_page_config(
    page_title="Lab Assistant", 
    page_icon="🧪", 
    layout="wide"
)

# Initialize Anthropic Client
client = anthropic.Anthropic(api_key=API_KEY)

# --- 3. HELPER FUNCTIONS ---

def encode_file(uploaded_file):
    """Convert uploaded file (Image/PDF) to base64 string for the API."""
    try:
        # Reset file pointer to the beginning
        uploaded_file.seek(0)
        return base64.b64encode(uploaded_file.read()).decode('utf-8')
    except Exception as e:
        st.error(f"Error encoding file: {e}")
        return None

def get_media_type(filename):
    """Determine the correct media type based on file extension."""
    ext = filename.lower().split('.')[-1]
    media_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp',
        'pdf': 'application/pdf'
    }
    # Default to jpeg if unknown
    return media_types.get(ext, 'image/jpeg')

def grade_submission(file, rubric_text):
    """Sends the file and rubric to Claude Sonnet 4.5 for analysis."""
    
    base64_data = encode_file(file)
    if not base64_data:
        return "Error: Could not process file."
        
    media_type = get_media_type(file.name)
    
    # Construct the message payload
    user_message_content = [
        {
            "type": "text",
            "text": (
                f"Please grade this lab report based on the rubric provided below.\n\n"
                f"--- RUBRIC START ---\n{rubric_text}\n--- RUBRIC END ---\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Analyze the graphs and figures visually. Are they scientifically standard?\n"
                f"2. Check the data values against the conclusion.\n"
                f"3. Provide the output in the strict format requested in the system prompt."
            )
        },
        {
            "type": "document" if media_type == 'application/pdf' else "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data
            }
        }
    ]

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=3000,  # Generous token limit for detailed scientific analysis
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message_content}]
        )
        return response.content[0].text
    except anthropic.APIError as e:
        return f"⚠️ API Error: {str(e)}"
    except Exception as e:
        return f"⚠️ Unexpected Error: {str(e)}"

def parse_score(text):
    """Helper to extract the score for the summary table."""
    try:
        lines = text.split('\n')
        for line in lines:
            if "SCORE:" in line:
                # Returns everything after "SCORE:"
                return line.split("SCORE:")[1].strip()
    except:
        pass
    return "N/A"

# --- 4. SIDEBAR (CONTROLS) ---
with st.sidebar:
    st.header("⚙️ Lab Assistant Controls")
    
    st.info("Define your grading criteria below. Be specific about points for graphs, sig figs, and accuracy.")
    
    # Default placeholder rubric
    default_rubric = """1. Data Presentation (10 pts):
- Graphs have titles, labeled axes, and units
- Data points are clearly visible
- Significant figures are consistent

2. Scientific Analysis (10 pts):
- Trendline/Slope calculation is correct
- Error analysis identifies primary sources of error

3. Conclusion (5 pts):
- Claim is supported by evidence in the graphs"""

    rubric_input = st.text_area("📋 Grading Rubric", value=default_rubric, height=400)
    
    st.divider()
    st.caption(f"🤖 Model: {MODEL_NAME}")
    st.caption("Capabilities: Graph Analysis, Handwriting Recognition, PDF Reading")

# --- 5. MAIN INTERFACE ---
st.title("🧪 Lab Assistant")
st.markdown("### Batch Grading & Scientific Data Analysis")
st.markdown("""
Upload student lab reports (Images or PDFs). This assistant will:
1. **Audit Graphs:** Check axes, units, and scales.
2. **Verify Math:** Check visible calculations (slope, molarity, etc.).
3. **Grade:** Apply your rubric and generate feedback.
""")

st.divider()

# File Uploader
uploaded_files = st.file_uploader(
    "📂 Upload Student Reports", 
    type=['png', 'jpg', 'jpeg', 'pdf'], 
    accept_multiple_files=True
)

# Action Area
col1, col2 = st.columns([1, 4])
with col1:
    start_btn = st.button("🚀 Start Grading", type="primary", use_container_width=True, disabled=not (uploaded_files and rubric_input))

# --- 6. EXECUTION LOGIC ---
if start_btn and uploaded_files and rubric_input:
    
    st.write("---")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    results_data = []
    
    # Create Tabs for Output
    tab_summary, tab_details = st.tabs(["📊 Gradebook Summary", "📝 Detailed Feedback"])

    # Processing Loop
    for i, file in enumerate(uploaded_files):
        status_text.markdown(f"**Analyzing report {i + 1}/{len(uploaded_files)}:** `{file.name}`...")
        
        # 1. Grade the file
        feedback = grade_submission(file, rubric_input)
        
        # 2. Extract score
        score = parse_score(feedback)
        
        # 3. Save result
        results_data.append({
            "Filename": file.name,
            "Score": score,
            "Full Feedback": feedback
        })
        
        # 4. Update Progress
        progress_bar.progress((i + 1) / len(uploaded_files))
        
        # Optional: slight delay to be kind to rate limits if grading many files
        # time.sleep(0.5)

    status_text.success("✅ Batch Analysis Complete!")
    progress_bar.empty()

    # --- 7. DISPLAY RESULTS ---
    
    # Tab 1: Summary Dataframe
    with tab_summary:
        st.subheader("Class Overview")
        df = pd.DataFrame(results_data)
        
        # Display interactive table
        st.dataframe(
            df[["Filename", "Score"]], 
            use_container_width=True,
            hide_index=True
        )
        
        # CSV Download Button
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Gradebook (CSV)",
            data=csv,
            file_name='lab_assistant_grades.csv',
            mime='text/csv',
        )

    # Tab 2: Detailed Views
    with tab_details:
        st.subheader("Individual Report Analysis")
        for item in results_data:
            with st.expander(f"📄 {item['Filename']} (Score: {item['Score']})"):
                st.markdown(item['Full Feedback'])

elif start_btn and not rubric_input:
    st.error("⚠️ Please provide a grading rubric in the sidebar before starting.")
import streamlit as st
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json
from datetime import datetime
import io

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file'] # Access Docs and create files
# Use secrets for credentials
try:
    # This structure matches how secrets are accessed from secrets.toml
    CLIENT_CONFIG = st.secrets["google_credentials"]["web"]
    # Ensure keys match the downloaded credentials.json format
    CLIENT_CONFIG_JSON = json.dumps({"web": CLIENT_CONFIG}) 
except KeyError:
    st.error("Google Credentials not found in Streamlit Secrets. Please configure secrets.toml.")
    st.stop()
except Exception as e:
    st.error(f"Error loading credentials from secrets: {e}")
    st.stop()
    
# Determine Redirect URI - Use App URL for deployed apps, localhost for local testing
# This is often tricky. For Streamlit Cloud, you might need to use 'Out Of Band' (oob) flow
# or set the deployed app's URL as the redirect URI in Google Cloud Console.
# Using 'oob' for broader compatibility initially:
REDIRECT_URI_TYPE = 'urn:ietf:wg:oauth:2.0:oob' # Or your configured URL

PROJECT_DETAILS = {
    "Lead Company Name": "FLOX Limited",
    "Project title": "NetFLOX360 – Bridging Poultry Farm Data with Factory Insights using Artificial Intelligence for Sustainable Growth",
    "Project Number": "10103645",
    "Total Quarters": 4
    # Add other details if needed by the chatbot
}

# Report sections (simplified for chatbot flow)
report_section_keys = [
    "overall_summary", "progress", "issues_actions", "scope", "time",
    "cost", "exploitation", "risk_management", "project_planning",
    "next_quarter_forecast", 
    # Note: Handling the detailed progress table is very difficult in a pure chat flow.
    # It might be better to ask for a summary or handle it outside the bot.
]
report_section_prompts = {
    "start": "Welcome! Which reporting quarter (1-{0}) are you working on?".format(PROJECT_DETAILS['Total Quarters']),
    "quarter_end_date": "What is the end date for this quarter (YYYY-MM-DD)?",
    "overall_summary": "Okay, let's start with the 'Overall Summary'. Please provide brief points on Scope, Time, Cost, Exploitation, Risk, and PM status.",
    "progress": "Next, tell me about 'Progress'. What were the highlights, achievements, and overall successes this quarter?",
    "issues_actions": "Now for 'Issues and Actions'. Briefly list any key issues and the actions taken or planned. Do you need any help from the Monitoring Officer?",
    "scope": "Let's discuss 'Scope'. Has it remained aligned with the original plan? Any changes, concerns, or deviations? Are technical objectives still on track?",
    "time": "How about 'Time'? Which deliverables/milestones were due? Were they achieved? If delayed, please explain the reason, impact, and corrective actions.",
     "cost": "Now for the 'Cost' summary. Please provide a general statement on costs vs forecast and explain any significant variances (>5-10%) per partner.",
    "exploitation": "Tell me about 'Exploitation' activities this quarter (market engagement, IP progress, dissemination, etc.).",
    "risk_management": "What are the updates regarding 'Risk Management'? Any new/retired risks, changes in impact/likelihood? What are the biggest risks now?",
    "project_planning": "How has 'Project Planning' been? Describe team collaboration, PM challenges, and any improvements made. Has the Gantt chart been updated?",
    "next_quarter_forecast": "Finally, what is the 'Updated forecast for next quarter'? Main activities, challenges, and scheduled deliverables?",
    "upload_request": "For context (e.g., for Risk or Time sections), you might need to refer to specific documents. If you need to upload one now, use the uploader below. **Note: Uploaded files are only available during this session.**",
    "ready_to_generate": "I have collected information for all sections. Are you ready to generate the Google Doc draft?",
    "generation_complete": "Done! You can find the draft document '{0}' in your Google Drive.",
    "error": "Sorry, something went wrong. Please try again."
    # Add prompts for specific file requests if needed
}

# --- Google Authentication ---
def get_credentials():
    """Gets user credentials using OAuth 2.0 flow."""
    if 'credentials' in st.session_state and st.session_state.credentials.valid:
        return st.session_state.credentials

    # Use io.StringIO to load the config from the string derived from secrets
    flow = Flow.from_client_config(json.loads(CLIENT_CONFIG_JSON), scopes=SCOPES, redirect_uri=REDIRECT_URI_TYPE)
    
    if REDIRECT_URI_TYPE == 'urn:ietf:wg:oauth:2.0:oob':
        # Use Out-of-Band flow (user copies code)
        auth_url, _ = flow.authorization_url(prompt='consent')
        st.warning(f"Please go to this URL to authorize the application:\n{auth_url}")
        auth_code = st.text_input("Enter the authorization code here:")
        if auth_code:
            try:
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials
                st.experimental_rerun() # Rerun to update state after getting creds
                return flow.credentials
            except Exception as e:
                st.error(f"Error fetching token: {e}")
                return None
        else:
            return None # Waiting for user input
    else:
        # Standard web flow (more complex with Streamlit Cloud redirects)
        # ... implementation would go here ...
        st.error("Standard web auth flow not fully implemented for this example. Consider using 'oob'.")
        return None


# --- Google Docs API Function ---
def create_google_doc(credentials, quarter_number, answers):
    """Creates a new Google Doc with the report content."""
    try:
        service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials) # Need drive service to set title

        title = f"Innovate UK Q{quarter_number} Report - {PROJECT_DETAILS['Project Number']} - Draft {datetime.now().strftime('%Y%m%d_%H%M')}"
        
        # Basic document structure
        body = {'title': title}
        doc = service.documents().create(body=body).execute()
        doc_id = doc.get('documentId')

        st.write(f"Created document with ID: {doc_id}") # Debugging

        # Prepare content requests
        requests = [
            {'insertText': {'location': {'index': 1}, 'text': f"# Innovate UK Quarterly Report - Q{quarter_number}\n\n"}},
             {'insertText': {'location': {'index': 1}, 'text': f"**Project:** {PROJECT_DETAILS['Project title']} ({PROJECT_DETAILS['Project Number']})\n"}},
             {'insertText': {'location': {'index': 1}, 'text': f"**Quarter End Date:** {answers.get('quarter_end_date', 'N/A')}\n\n---\n\n"}},
        ]

        # Add sections dynamically
        offset = len(requests[0]['insertText']['text']) + len(requests[1]['insertText']['text']) + len(requests[2]['insertText']['text']) +1 # Track insertion point

        for key in report_section_keys:
             section_title = key.replace('_', ' ').title()
             content = answers.get(key, '*No data entered*') + "\n\n---\n\n"
             requests.append({'insertText': {'location': {'index': offset}, 'text': f"## {section_title}\n\n{content}"}})
             offset += len(f"## {section_title}\n\n{content}")
        
        # Ensure requests are ordered by index DESCENDING for safe insertion if indexes were complex
        # But since we append and calculate offset, ASCENDING works here.
        
        # Batch update - note Google Docs API processes requests sequentially based on list order.
        # Ensure your calculated offsets are correct for sequential insertion at a *growing* index.
        # Simpler approach: Insert sections one by one or build the full text first.

        # Let's try building full text first for simplicity:
        full_text = f"# Innovate UK Quarterly Report - Q{quarter_number}\n\n"
        full_text += f"**Project:** {PROJECT_DETAILS['Project title']} ({PROJECT_DETAILS['Project Number']})\n"
        full_text += f"**Quarter End Date:** {answers.get('quarter_end_date', 'N/A')}\n\n---\n\n"
        for key in report_section_keys:
            section_title = key.replace('_', ' ').title()
            content = answers.get(key, '*No data entered*')
            full_text += f"## {section_title}\n\n{content}\n\n---\n\n"

        requests = [{'insertText': {'location': {'index': 1}, 'text': full_text}}]


        # Apply updates
        result = service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        st.success(f"Successfully updated Google Doc.")
        return title # Return title for confirmation message

    except HttpError as error:
        st.error(f"An error occurred with Google Docs API: {error}")
        return None
    except Exception as e:
         st.error(f"An unexpected error occurred: {e}")
         return None

# --- Initialize Streamlit Session State ---
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'stage' not in st.session_state:
    st.session_state.stage = "start" # Control conversation flow
if 'current_quarter' not in st.session_state:
    st.session_state.current_quarter = None
if 'current_section_index' not in st.session_state:
     st.session_state.current_section_index = 0
if 'answers' not in st.session_state:
    st.session_state.answers = {} # Store collected answers here
if 'credentials' not in st.session_state:
    st.session_state.credentials = None # Store Google credentials
if 'uploaded_files_info' not in st.session_state:
    st.session_state.uploaded_files_info = {} # Store info about uploaded files this session

# --- App Layout ---
st.title("Innovate UK Grant Reporting Chatbot")
st.write(f"Assisting with: {PROJECT_DETAILS['Project title']}")

# --- Authentication Section ---
st.sidebar.title("Google Authentication")
if st.session_state.credentials and st.session_state.credentials.valid:
    st.sidebar.success("Authenticated with Google.")
    # Optional: Add logout button
    if st.sidebar.button("Logout Google"):
         st.session_state.credentials = None
         st.experimental_rerun()
else:
    st.sidebar.warning("Not authenticated with Google.")
    if st.sidebar.button("Login with Google"):
        # Attempt to get credentials - this might involve user interaction via text input
        get_credentials()
        # The rerun should happen within get_credentials if auth code is entered

# --- File Uploader Section ---
# Only show uploader when requested or relevant?
# Placed in sidebar for now for easier access during chat.
st.sidebar.divider()
st.sidebar.subheader("File Upload (Session Only)")
uploaded_file = st.sidebar.file_uploader(
    "Upload relevant documents when asked",
    type=['pdf', 'docx', 'xlsx', 'png', 'jpg'],
    key="file_uploader"
)
if uploaded_file:
    st.session_state.uploaded_files_info[uploaded_file.name] = {
        "type": uploaded_file.type,
        "size": uploaded_file.size
        # Don't store the buffer itself in session state - too large
    }
    st.sidebar.success(f"File '{uploaded_file.name}' ready for this session.")
    # Ideally, could try text extraction here and store text if needed
    # For now, just acknowledge upload. Bot needs to know what to do with it.


# --- Display Chat History ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Handle Chat Input ---
if prompt := st.chat_input("Your answer or command..."):
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Bot Logic based on stage
    current_stage = st.session_state.stage
    bot_response = ""

    try:
        if current_stage == "start":
            try:
                quarter = int(prompt)
                if 1 <= quarter <= PROJECT_DETAILS['Total Quarters']:
                    st.session_state.current_quarter = quarter
                    st.session_state.answers = {} # Reset answers for new quarter
                    st.session_state.current_section_index = 0 # Start asking sections
                    st.session_state.stage = "ask_section"
                     # Ask first section prompt immediately after setting stage
                    current_key = report_section_keys[st.session_state.current_section_index]
                    bot_response = report_section_prompts.get(current_key, "Please provide details for the next section.")
                     # Ask for quarter end date first
                    # bot_response = report_section_prompts["quarter_end_date"]
                    # st.session_state.stage = "get_quarter_end_date"
                else:
                    bot_response = f"Please enter a valid quarter number (1-{PROJECT_DETAILS['Total Quarters']})."
            except ValueError:
                bot_response = "Please enter a number for the quarter."

        elif current_stage == "get_quarter_end_date":
             # Add validation if needed
             st.session_state.answers["quarter_end_date"] = prompt
             st.session_state.current_section_index = 0
             st.session_state.stage = "ask_section"
             current_key = report_section_keys[st.session_state.current_section_index]
             bot_response = report_section_prompts.get(current_key, "...") # Ask first real section

        elif current_stage == "ask_section":
            # Save answer for the *previous* section asked
            last_section_index = st.session_state.current_section_index
            last_key = report_section_keys[last_section_index]
            st.session_state.answers[last_key] = prompt # Store user's answer

            # Move to next section
            st.session_state.current_section_index += 1

            if st.session_state.current_section_index < len(report_section_keys):
                # Ask next question
                next_key = report_section_keys[st.session_state.current_section_index]
                bot_response = report_section_prompts.get(next_key, "Please provide details for the next section.")
                 # Optional: Ask for file upload if relevant to the next_key
                 # if next_key in ["time", "risk_management"]:
                 #     bot_response += "\n\n" + report_section_prompts["upload_request"]
            else:
                # All sections done
                st.session_state.stage = "confirm_generate"
                bot_response = report_section_prompts["ready_to_generate"]

        elif current_stage == "confirm_generate":
            if prompt.lower() in ["yes", "y", "ok", "generate"]:
                if not st.session_state.credentials or not st.session_state.credentials.valid:
                     bot_response = "Please log in with Google first using the sidebar button before generating the document."
                     # Try to initiate login if possible? Requires rerun logic.
                     # get_credentials() # This might not work smoothly here. Best to instruct user.
                else:
                    st.session_state.stage = "generating"
                    # Show spinner while generating
                    with st.spinner("Generating Google Doc..."):
                         doc_title = create_google_doc(
                             st.session_state.credentials,
                             st.session_state.current_quarter,
                             st.session_state.answers
                         )
                    if doc_title:
                         bot_response = report_section_prompts["generation_complete"].format(doc_title)
                         st.session_state.stage = "done" # Or loop back to start?
                    else:
                         bot_response = report_section_prompts["error"] + " Failed to create document."
                         st.session_state.stage = "confirm_generate" # Allow retry?
            else:
                bot_response = "Okay, let me know when you're ready to generate the document."
                # Stay in confirm_generate stage

        # Handle other stages if needed (e.g., 'done', 'error')

        else: # Default / Error stage
             bot_response = report_section_prompts.get("error", "Sorry, I'm not sure how to proceed.")
             st.session_state.stage = "start" # Reset

    except Exception as e:
         st.error(f"An error occurred in the bot logic: {e}")
         bot_response = report_section_prompts.get("error", "An unexpected error occurred.")
         # Optionally reset stage
         # st.session_state.stage = "start"


    # Add bot response to history
    if bot_response:
        st.session_state.messages.append({"role": "assistant", "content": bot_response})
        # Rerun immediately to show the bot response and update the UI state
        st.rerun()
    # If no bot response generated (e.g., waiting for auth code), don't rerun yet


# --- Initial Bot Prompt ---
# Ensure the initial prompt is added only once or when the stage resets to 'start'
if not st.session_state.messages:
     initial_prompt = report_section_prompts["start"]
     st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
     st.rerun() # Rerun to display initial message
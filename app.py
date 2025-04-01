import streamlit as st
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json # Keep json import, might be useful elsewhere
from datetime import datetime
import io
import sys # To check Python version if needed

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file'] # Access Docs and create files

# --- Robust Credential Loading and Conversion ---
try:
    # 1. Access the secrets section
    google_creds_section = st.secrets["google_credentials"]
    
    # 2. Check if 'web' key exists
    if "web" not in google_creds_section:
        st.error("Missing 'web' section within `[google_credentials]` in Streamlit Secrets.")
        st.stop()
        
    web_config_from_secrets = google_creds_section["web"]

    # --- Explicitly build a standard Python dictionary ---
    # This avoids issues with AttrDict potentially persisting
    web_config_dict = {}
    required_keys = ["client_id", "project_id", "auth_uri", "token_uri", "client_secret"]
    
    # Check for redirect_uris in the secrets object and add if present
    if hasattr(web_config_from_secrets, 'redirect_uris') or 'redirect_uris' in web_config_from_secrets:
         required_keys.append('redirect_uris')

    missing_keys = []
    for key in required_keys:
        # Access attributes robustly, checking existence first
        if hasattr(web_config_from_secrets, key):
             web_config_dict[key] = getattr(web_config_from_secrets, key)
        elif key in web_config_from_secrets: # Fallback check if it's dict-like
             web_config_dict[key] = web_config_from_secrets[key]
        else:
             missing_keys.append(key)
             
    if missing_keys:
        st.error(f"Google Credentials in Streamlit Secrets are missing required keys in the 'web' section: {missing_keys}. Please check your secrets configuration.")
        st.stop()
        
    # Ensure redirect_uris is a list if it exists (TOML array becomes list)
    if 'redirect_uris' in web_config_dict and not isinstance(web_config_dict['redirect_uris'], list):
        st.error("Configuration error: 'redirect_uris' in secrets should be a list (e.g., `web.redirect_uris = [\"url1\"]`).")
        # Attempt to fix if it's a single string (common mistake)
        if isinstance(web_config_dict['redirect_uris'], str):
             st.warning("Attempting to fix redirect_uris: treating single string as a list.")
             web_config_dict['redirect_uris'] = [web_config_dict['redirect_uris']]
        else:
             st.stop() # Stop if it's some other invalid type

    # Debugging (Optional: Uncomment temporarily in Streamlit Cloud logs if needed)
    # st.write("DEBUG: Type of web_config_from_secrets:", type(web_config_from_secrets))
    # st.write("DEBUG: Type of web_config_dict:", type(web_config_dict))
    # st.write("DEBUG: Content of web_config_dict:", web_config_dict)

    # This is the dictionary we will pass to the Flow function
    FULL_CLIENT_CONFIG_DICT = {"web": web_config_dict}

except KeyError:
    st.error("Could not find `[google_credentials]` or `[google_credentials.web]` section in Streamlit Secrets. Ensure it's configured correctly in TOML format.")
    st.stop()
except AttributeError:
     st.error("AttributeError accessing secrets. Check `[google_credentials.web]` structure in TOML.")
     st.stop()
except Exception as e:
    st.error(f"Error processing credentials from secrets: {e}")
    # Optionally print more debug info
    # import traceback
    # st.error(traceback.format_exc())
    st.stop()

# --- Rest of the Configuration (Unchanged) ---
REDIRECT_URI_TYPE = 'urn:ietf:wg:oauth:2.0:oob' # Or your configured URL if not using oob

PROJECT_DETAILS = {
    "Lead Company Name": "FLOX Limited",
    "Project title": "NetFLOX360 – Bridging Poultry Farm Data with Factory Insights using Artificial Intelligence for Sustainable Growth",
    "Project Number": "10103645",
    "Total Quarters": 4
}

report_section_keys = [
    "quarter_end_date", 
    "overall_summary", "progress", "issues_actions", "scope", "time",
    "cost", "exploitation", "risk_management", "project_planning",
    "next_quarter_forecast",
]
report_section_prompts = {
    "start": "Welcome! I can help you draft your Innovate UK Quarterly Report for NetFLOX360. Which reporting quarter (1-{0}) are you working on?".format(PROJECT_DETAILS['Total Quarters']),
    "quarter_end_date": "Great! What is the end date for Quarter {0} (YYYY-MM-DD)?",
    "overall_summary": "Okay, let's start with the 'Overall Summary'. Please provide brief points on Scope, Time, Cost, Exploitation, Risk, and PM status.",
    "progress": "Next, tell me about 'Progress'. What were the highlights, achievements, and overall successes this quarter?",
    "issues_actions": "Now for 'Issues and Actions'. Briefly list any key issues and the actions taken or planned. Do you need any help from the Monitoring Officer?",
    "scope": "Let's discuss 'Scope'. Has it remained aligned with the original plan? Any changes, concerns, or deviations? Are technical objectives still on track?",
    "time": "How about 'Time'? Which deliverables/milestones were due? Were they achieved? If delayed, please explain the reason, impact, and corrective actions.",
     "cost": "Now for the 'Cost' summary. Please provide a general statement on costs vs forecast and explain any significant variances (>5-10%) per partner.",
    "exploitation": "Tell me about 'Exploitation' activities this quarter (market engagement, IP progress, dissemination, etc.).",
    "risk_management": "What are the updates regarding 'Risk Management'? Any new/retired risks, changes in impact/likelihood? What are the biggest risks now? You may want to upload your Risk Register using the sidebar.",
    "project_planning": "How has 'Project Planning' been? Describe team collaboration, PM challenges, and any improvements made. Has the Gantt chart been updated?",
    "next_quarter_forecast": "Finally, what is the 'Updated forecast for next quarter'? Main activities, challenges, and scheduled deliverables?",
    "upload_request": "For context (e.g., for Risk or Time sections), you might need to refer to specific documents. If you need to upload one now, use the uploader in the sidebar. **Note: Uploaded files are only available during this session.**",
    "ready_to_generate": "I have collected information for all sections for Q{0}. Are you ready to generate the Google Doc draft? (Type 'yes' to confirm)",
    "generation_complete": "Done! You can find the draft document titled '{0}' in your Google Drive.",
    "error": "Sorry, something went wrong. Please try again or contact support if the issue persists."
}

# --- Google Authentication (Unchanged from previous version) ---
def get_credentials():
    """Gets user credentials using OAuth 2.0 flow."""
    if 'credentials' in st.session_state and st.session_state.credentials and st.session_state.credentials.valid:
         return st.session_state.credentials

    try:
        flow = Flow.from_client_config(
            FULL_CLIENT_CONFIG_DICT, # Pass the manually constructed dictionary
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI_TYPE
        )
    except ValueError as e:
        st.error(f"Error creating OAuth Flow. Check credentials format in Secrets: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error creating OAuth Flow: {e}")
        return None

    if REDIRECT_URI_TYPE == 'urn:ietf:wg:oauth:2.0:oob':
        auth_url, _ = flow.authorization_url(prompt='consent')
        st.warning(f"""
        **Action Required: Authorize Google Access**

        1.  Go to this URL: [Google Authorization Link]({auth_url})
        2.  Grant the requested permissions.
        3.  Copy the authorization code provided by Google.
        4.  Paste the code into the input box below.
        """)
        auth_code = st.text_input("Enter the authorization code from Google here:", key="google_auth_code_input", type="password")

        if auth_code:
            try:
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials
                st.success("Google authentication successful!")
                st.rerun() 
                return flow.credentials
            except Exception as e:
                st.error(f"Error fetching token with provided code. Was the code pasted correctly? Error: {e}")
                if 'credentials' in st.session_state:
                    del st.session_state['credentials']
                return None
        else:
            st.info("Waiting for authorization code entry...")
            return None 
    else:
        st.error("Standard web auth flow not fully implemented for this example. Using 'oob' flow.")
        return None

# --- Google Docs API Function (Unchanged from previous version) ---
def create_google_doc(credentials, quarter_number, answers):
    """Creates a new Google Doc with the report content."""
    if not credentials or not credentials.valid:
        st.error("Invalid Google credentials provided for document creation.")
        return None
        
    try:
        service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials) 

        title = f"Innovate UK Q{quarter_number} Report - {PROJECT_DETAILS['Project Number']} - Draft {datetime.now().strftime('%Y%m%d_%H%M')}"

        body = {'title': title}
        doc = service.documents().create(body=body).execute()
        doc_id = doc.get('documentId')
        if not doc_id:
            st.error("Failed to create Google Doc: No document ID returned.")
            return None

        full_text = f"# Innovate UK Quarterly Report - Q{quarter_number}\n\n"
        full_text += f"**Project:** {PROJECT_DETAILS['Project title']} ({PROJECT_DETAILS['Project Number']})\n"
        full_text += f"**Quarter End Date:** {answers.get('quarter_end_date', 'N/A')}\n\n---\n\n"
        for key in report_section_keys:
            if key == "quarter_end_date": continue 
            section_title = key.replace('_', ' ').title()
            content = answers.get(key)
            if not content: 
                content = "*No data entered for this section.*"
            full_text += f"## {section_title}\n\n{content}\n\n---\n\n"

        requests = [{'insertText': {'location': {'index': 1}, 'text': full_text}}]

        result = service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        st.success(f"Successfully created and populated Google Doc.")
        
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        st.markdown(f"**[Open Generated Document]({doc_url})**", unsafe_allow_html=True)
        
        return title 

    except HttpError as error:
        st.error(f"An error occurred with Google Docs/Drive API: {error}")
        error_details = getattr(error, 'resp', {}).get('content', '{}')
        try:
             error_json = json.loads(error_details)
             st.json(error_json) 
        except:
             st.write(f"Raw error content: {error_details}") 
        return None
    except Exception as e:
         st.error(f"An unexpected error occurred during document creation: {e}")
         return None

# --- Initialize Streamlit Session State (Unchanged) ---
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'stage' not in st.session_state:
    st.session_state.stage = "start" 
if 'current_quarter' not in st.session_state:
    st.session_state.current_quarter = None
if 'current_section_index' not in st.session_state:
     st.session_state.current_section_index = 0
if 'answers' not in st.session_state:
    st.session_state.answers = {} 
if 'credentials' not in st.session_state:
    st.session_state.credentials = None 
if 'uploaded_files_info' not in st.session_state:
    st.session_state.uploaded_files_info = {}

# --- App Layout (Unchanged) ---
st.set_page_config(page_title="IUK Grant Bot", layout="centered") 
st.title("Innovate UK Grant Reporting Chatbot")
st.write(f"Assisting with: {PROJECT_DETAILS['Project title']}")
st.caption("This bot guides you through report sections conversationally and generates a Google Doc draft.")

st.sidebar.title("Google Authentication")
creds = st.session_state.get('credentials')
if creds and creds.valid:
    st.sidebar.success("Authenticated with Google.")
    if st.sidebar.button("Logout Google"):
         st.session_state.credentials = None
         st.rerun()
else:
    st.sidebar.warning("Not authenticated with Google.")
    if st.sidebar.button("Login with Google"):
        get_credentials() 

st.sidebar.divider()
st.sidebar.subheader("File Upload (Session Only)")
uploaded_file = st.sidebar.file_uploader(
    "Upload relevant documents when asked",
    type=['pdf', 'docx', 'xlsx', 'png', 'jpg', 'txt'], 
    key="file_uploader_widget", 
    help="Files uploaded here are only available during the current session and are not stored long-term."
)
if uploaded_file:
    MAX_FILE_SIZE_MB = 5
    if uploaded_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        st.sidebar.error(f"File size exceeds {MAX_FILE_SIZE_MB}MB limit.")
    else:
        st.session_state.uploaded_files_info[uploaded_file.name] = {
            "type": uploaded_file.type,
            "size": uploaded_file.size
        }
        st.sidebar.success(f"File '{uploaded_file.name}' available for this session.")

# --- Display Chat History (Unchanged) ---
chat_container = st.container() 
with chat_container:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# --- Handle Chat Input (Unchanged from previous version) ---
if prompt := st.chat_input("Your answer or command...", key="chat_input_widget"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    current_stage = st.session_state.stage
    bot_response = ""
    trigger_rerun = True 

    try:
        if current_stage == "start":
            try:
                quarter = int(prompt)
                if 1 <= quarter <= PROJECT_DETAILS['Total Quarters']:
                    st.session_state.current_quarter = quarter
                    st.session_state.answers = {} 
                    st.session_state.current_section_index = 0 
                    st.session_state.stage = "ask_section"
                    current_key = report_section_keys[st.session_state.current_section_index]
                    bot_response = report_section_prompts.get(current_key, "...").format(st.session_state.current_quarter) 
                else:
                    bot_response = f"Please enter a valid quarter number (1-{PROJECT_DETAILS['Total Quarters']})."
            except ValueError:
                bot_response = "Please enter a number for the quarter."

        elif current_stage == "ask_section":
            last_section_index = st.session_state.current_section_index
            last_key = report_section_keys[last_section_index]
            if not prompt and last_key != "optional_section_key_if_any": 
                 bot_response = f"Please provide some input for the '{last_key.replace('_',' ').title()}' section."
                 trigger_rerun = True 
            else:
                 st.session_state.answers[last_key] = prompt 
                 st.session_state.current_section_index += 1
                 if st.session_state.current_section_index < len(report_section_keys):
                     next_key = report_section_keys[st.session_state.current_section_index]
                     bot_response = report_section_prompts.get(next_key, "...")
                     if next_key in ["time", "risk_management", "cost"]: 
                          bot_response += "\n\n" + report_section_prompts["upload_request"]
                 else:
                     st.session_state.stage = "confirm_generate"
                     bot_response = report_section_prompts["ready_to_generate"].format(st.session_state.current_quarter)

        elif current_stage == "confirm_generate":
            if prompt.lower() in ["yes", "y", "ok", "generate", "confirm"]:
                creds = get_credentials() 
                if not creds or not creds.valid:
                     bot_response = "Authentication needed. Please use the 'Login with Google' button in the sidebar first."
                     trigger_rerun = False # Wait for user to click login
                else:
                    st.session_state.stage = "generating"
                    bot_response = "Okay, generating the Google Doc now..." 
            else:
                bot_response = "Okay, I won't generate the document yet. Let me know when you're ready."

        elif current_stage == "generating":
             creds = get_credentials() 
             if creds and creds.valid:
                 with st.spinner("Creating and populating Google Doc... This may take a moment."):
                      doc_title = create_google_doc(
                          creds,
                          st.session_state.current_quarter,
                          st.session_state.answers
                      )
                 if doc_title:
                      bot_response = report_section_prompts["generation_complete"].format(doc_title)
                      st.session_state.stage = "done" 
                 else:
                      bot_response = report_section_prompts["error"] + " Failed during document creation. Please check permissions or try again."
                      st.session_state.stage = "confirm_generate" 
             else:
                 bot_response = "Google authentication failed or expired. Please log in again via the sidebar before generating."
                 st.session_state.stage = "confirm_generate" 
             trigger_rerun = True 


        elif current_stage == "done":
            bot_response = "You can now start a new report by telling me the quarter number."
            st.session_state.stage = "start" 

        else: 
             bot_response = report_section_prompts.get("error", "Sorry, I'm in an unknown state. Let's start over.")
             st.session_state.stage = "start" 

    except Exception as e:
         st.error(f"An unexpected error occurred in the chatbot logic: {e}")
         bot_response = report_section_prompts.get("error", "An unexpected error occurred. Resetting.")
         st.session_state.stage = "start" 


    if bot_response:
        st.session_state.messages.append({"role": "assistant", "content": bot_response})
    if trigger_rerun:
        st.rerun()


# --- Initial Bot Prompt (Unchanged) ---
if not st.session_state.messages or st.session_state.stage == "start":
     if st.session_state.messages and st.session_state.stage == "start": # If reset to start, clear history?
          st.session_state.messages = [] # Uncomment to clear history on reset
          
     initial_prompt = report_section_prompts["start"]
     if not st.session_state.messages or st.session_state.messages[-1].get("content") != initial_prompt:
         st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
         st.rerun() 

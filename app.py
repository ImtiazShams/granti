import streamlit as st
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json
from datetime import datetime
import io
import sys
import traceback # Import traceback for detailed error logging

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']

# --- Robust Credential Loading and Conversion with Debugging ---
FULL_CLIENT_CONFIG_DICT = None # Initialize
print("--- Attempting to load credentials from secrets ---")

try:
    # 1. Check if secrets object exists and has the key
    if not hasattr(st, 'secrets') or "google_credentials" not in st.secrets:
        err_msg = "Streamlit secrets object 'st.secrets' not found or missing '[google_credentials]' section."
        print(f"ERROR: {err_msg}")
        st.error(err_msg + " Please check Streamlit Cloud Secrets configuration.")
        st.stop()

    google_creds_section = st.secrets["google_credentials"]
    print(f"DEBUG: Type of google_creds_section: {type(google_creds_section)}")
    # print(f"DEBUG: Content of google_creds_section: {google_creds_section}") # Might be too verbose/sensitive for logs

    # 2. Check if 'web' key exists within the section
    if "web" not in google_creds_section:
        err_msg = "Missing 'web' section within `[google_credentials]` in Streamlit Secrets."
        print(f"ERROR: {err_msg}")
        st.error(err_msg)
        st.stop()

    web_config_from_secrets = google_creds_section["web"]
    print(f"DEBUG: Type of web_config_from_secrets ('web' section): {type(web_config_from_secrets)}")
    # print(f"DEBUG: Content of web_config_from_secrets: {web_config_from_secrets}")

    # --- Explicitly build a standard Python dictionary ---
    web_config_dict = {}
    required_keys = ["client_id", "project_id", "auth_uri", "token_uri", "client_secret"]
    
    # Check if redirect_uris is present (might not be if using oob only)
    has_redirect_uris = hasattr(web_config_from_secrets, 'redirect_uris') or 'redirect_uris' in web_config_from_secrets
    if has_redirect_uris:
         required_keys.append('redirect_uris')

    print(f"DEBUG: Expecting keys: {required_keys}")

    missing_keys = []
    for key in required_keys:
        value = None
        # Try accessing as attribute first (common for AttrDict)
        if hasattr(web_config_from_secrets, key):
             value = getattr(web_config_from_secrets, key)
             print(f"DEBUG: Found key '{key}' via getattr, type: {type(value)}")
        # Fallback: Try accessing as dictionary key
        elif key in web_config_from_secrets:
             value = web_config_from_secrets[key]
             print(f"DEBUG: Found key '{key}' via dict access, type: {type(value)}")
        
        if value is not None:
            web_config_dict[key] = value
        else:
             print(f"DEBUG: Missing key '{key}'")
             missing_keys.append(key)

    if missing_keys:
        err_msg = f"Google Credentials in Streamlit Secrets are missing required keys in the 'web' section: {missing_keys}."
        print(f"ERROR: {err_msg}")
        st.error(err_msg + " Please check your secrets configuration.")
        st.stop()

    # Validate and potentially fix redirect_uris type
    if 'redirect_uris' in web_config_dict:
        if not isinstance(web_config_dict['redirect_uris'], list):
            err_msg = "Configuration error: 'redirect_uris' in secrets should be a list (e.g., `web.redirect_uris = [\"url1\"]`)."
            print(f"ERROR: {err_msg}")
            st.error(err_msg)
            if isinstance(web_config_dict['redirect_uris'], str):
                 print("WARNING: Attempting to fix redirect_uris: treating single string as a list.")
                 st.warning("Attempting to fix redirect_uris format. Please ensure it's a list in secrets for future reliability.")
                 web_config_dict['redirect_uris'] = [web_config_dict['redirect_uris']]
            else:
                 st.stop() # Stop if it's some other invalid type
        print("DEBUG: redirect_uris processed as list.")


    print("DEBUG: Final web_config_dict content:")
    # Print safely, hiding secret
    debug_dict_safe = {k: (v if k != 'client_secret' else '***HIDDEN***') for k, v in web_config_dict.items()}
    print(debug_dict_safe)
    
    print("DEBUG: Type of final web_config_dict:", type(web_config_dict))

    # Final structure for the Flow
    FULL_CLIENT_CONFIG_DICT = {"web": web_config_dict}
    print("--- Credentials successfully processed into dictionary ---")

except KeyError as e:
    err_msg = f"KeyError accessing secrets: Missing key '{e}'. Check `[google_credentials.web]` structure."
    print(f"ERROR: {err_msg}")
    print(traceback.format_exc())
    st.error(err_msg)
    st.stop()
except AttributeError as e:
     err_msg = f"AttributeError accessing secrets: '{e}'. Check `[google_credentials.web]` structure/names."
     print(f"ERROR: {err_msg}")
     print(traceback.format_exc())
     st.error(err_msg)
     st.stop()
except Exception as e:
    err_msg = f"Unexpected error processing credentials from secrets: {e}"
    print(f"ERROR: {err_msg}")
    print(traceback.format_exc())
    st.error(err_msg)
    st.stop()

# --- Rest of the Configuration (Unchanged) ---
REDIRECT_URI_TYPE = 'urn:ietf:wg:oauth:2.0:oob' 

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

# --- Google Authentication ---
def get_credentials():
    """Gets user credentials using OAuth 2.0 flow."""
    print("--- Entering get_credentials function ---")
    if 'credentials' in st.session_state and st.session_state.credentials and st.session_state.credentials.valid:
         print("DEBUG: Valid credentials found in session state.")
         return st.session_state.credentials

    # Ensure FULL_CLIENT_CONFIG_DICT was loaded correctly
    if not FULL_CLIENT_CONFIG_DICT:
         err_msg = "Critical Error: FULL_CLIENT_CONFIG_DICT is not set. Cannot create OAuth Flow."
         print(f"ERROR: {err_msg}")
         st.error(err_msg)
         return None

    print("DEBUG: Creating OAuth Flow instance...")
    try:
        flow = Flow.from_client_config(
            FULL_CLIENT_CONFIG_DICT, # Pass the manually constructed dictionary
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI_TYPE
        )
        print("DEBUG: OAuth Flow instance created successfully.")
    except ValueError as e:
        err_msg = f"ValueError creating OAuth Flow. Check credentials dictionary structure: {e}"
        print(f"ERROR: {err_msg}")
        print(traceback.format_exc())
        st.error(err_msg)
        return None
    except Exception as e:
        err_msg = f"Unexpected error creating OAuth Flow: {e}"
        print(f"ERROR: {err_msg}")
        print(traceback.format_exc())
        st.error(err_msg)
        return None

    # Proceed with the selected OAuth flow type
    if REDIRECT_URI_TYPE == 'urn:ietf:wg:oauth:2.0:oob':
        print("DEBUG: Using 'oob' OAuth flow.")
        try:
             auth_url, _ = flow.authorization_url(prompt='consent')
             print("DEBUG: Authorization URL generated.")
        except Exception as e:
             err_msg = f"Error generating authorization URL: {e}"
             print(f"ERROR: {err_msg}")
             print(traceback.format_exc())
             st.error(err_msg)
             return None
             
        st.warning(f"""
        **Action Required: Authorize Google Access**

        1.  Go to this URL: [Google Authorization Link]({auth_url})
        2.  Grant the requested permissions.
        3.  Copy the authorization code provided by Google.
        4.  Paste the code into the input box below.
        """)
        auth_code = st.text_input("Enter the authorization code from Google here:", key="google_auth_code_input", type="password")

        if auth_code:
            print("DEBUG: Auth code entered by user. Attempting to fetch token...")
            try:
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials
                print("DEBUG: Token fetched successfully. Credentials stored in session.")
                st.success("Google authentication successful!")
                st.rerun() 
                return flow.credentials
            except Exception as e:
                err_msg = f"Error fetching token with provided code. Was the code pasted correctly? Error: {e}"
                print(f"ERROR: {err_msg}")
                print(traceback.format_exc()) # Print detailed traceback to logs
                st.error(err_msg)
                if 'credentials' in st.session_state:
                    del st.session_state['credentials']
                return None
        else:
            print("DEBUG: Waiting for user to enter authorization code.")
            st.info("Waiting for authorization code entry...")
            return None 
    else:
        err_msg = "Standard web auth flow not fully implemented for this example. Using 'oob' flow."
        print(f"ERROR: {err_msg}")
        st.error(err_msg)
        return None

# --- Google Docs API Function (Unchanged) ---
def create_google_doc(credentials, quarter_number, answers):
    """Creates a new Google Doc with the report content."""
    print("--- Entering create_google_doc function ---")
    if not credentials or not credentials.valid:
        err_msg = "Invalid Google credentials provided for document creation."
        print(f"ERROR: {err_msg}")
        st.error(err_msg)
        return None
        
    try:
        print("DEBUG: Building Google Docs and Drive services...")
        service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials) 
        print("DEBUG: Services built successfully.")

        title = f"Innovate UK Q{quarter_number} Report - {PROJECT_DETAILS['Project Number']} - Draft {datetime.now().strftime('%Y%m%d_%H%M')}"
        print(f"DEBUG: Attempting to create doc with title: {title}")

        body = {'title': title}
        doc = service.documents().create(body=body).execute()
        doc_id = doc.get('documentId')
        if not doc_id:
            err_msg = "Failed to create Google Doc: No document ID returned from API."
            print(f"ERROR: {err_msg}")
            st.error(err_msg)
            return None
        print(f"DEBUG: Google Doc created with ID: {doc_id}")

        print("DEBUG: Building report text content...")
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
        print(f"DEBUG: Report text built (length: {len(full_text)} chars).")

        print("DEBUG: Preparing batchUpdate request...")
        requests = [{'insertText': {'location': {'index': 1}, 'text': full_text}}]

        print(f"DEBUG: Executing batchUpdate for doc ID: {doc_id}...")
        result = service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print("DEBUG: batchUpdate executed successfully.")
        st.success(f"Successfully created and populated Google Doc.")
        
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        st.markdown(f"**[Open Generated Document]({doc_url})**", unsafe_allow_html=True)
        
        return title 

    except HttpError as error:
        err_msg = f"An error occurred with Google Docs/Drive API: {error}"
        print(f"ERROR: {err_msg}")
        error_details = getattr(error, 'resp', {}).get('content', '{}')
        print(f"ERROR DETAILS: {error_details}")
        st.error(err_msg)
        try:
             error_json = json.loads(error_details)
             st.json(error_json) 
        except:
             st.write(f"Raw error content: {error_details}") 
        return None
    except Exception as e:
         err_msg = f"An unexpected error occurred during document creation: {e}"
         print(f"ERROR: {err_msg}")
         print(traceback.format_exc())
         st.error(err_msg)
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
        # This button click *should* trigger the display of auth URL / code input box
        # by calling get_credentials() which contains the st.warning/st.text_input calls
        get_credentials() 
        # We might not have creds *immediately* after this click, user needs to interact

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

# --- Handle Chat Input ---
# Use a different key for the chat input to ensure it's distinct
if prompt := st.chat_input("Your answer or command...", key="chat_input_main"):
    print(f"DEBUG: User input received: '{prompt[:50]}...'") # Log user input safely
    st.session_state.messages.append({"role": "user", "content": prompt})

    current_stage = st.session_state.stage
    print(f"DEBUG: Current stage: {current_stage}")
    bot_response = ""
    trigger_rerun = True 

    try:
        # --- Bot Logic Stages --- 
        if current_stage == "start":
            print("DEBUG: Handling 'start' stage.")
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
            print(f"DEBUG: 'start' stage processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")

        elif current_stage == "ask_section":
            print(f"DEBUG: Handling 'ask_section' stage. Current section index: {st.session_state.current_section_index}")
            last_section_index = st.session_state.current_section_index
            last_key = report_section_keys[last_section_index]
            print(f"DEBUG: Saving answer for section: '{last_key}'")
            
            if not prompt and last_key not in ["optional_section_key_if_any"]: # Add actual optional keys if needed
                 bot_response = f"Please provide some input for the '{last_key.replace('_',' ').title()}' section."
                 trigger_rerun = True 
            else:
                 st.session_state.answers[last_key] = prompt 
                 st.session_state.current_section_index += 1
                 
                 if st.session_state.current_section_index < len(report_section_keys):
                     next_key = report_section_keys[st.session_state.current_section_index]
                     print(f"DEBUG: Asking for next section: '{next_key}'")
                     bot_response = report_section_prompts.get(next_key, "...")
                     if next_key in ["time", "risk_management", "cost"]: 
                          bot_response += "\n\n" + report_section_prompts["upload_request"]
                 else:
                     print("DEBUG: All sections collected. Moving to 'confirm_generate'.")
                     st.session_state.stage = "confirm_generate"
                     bot_response = report_section_prompts["ready_to_generate"].format(st.session_state.current_quarter)
            print(f"DEBUG: 'ask_section' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")

        elif current_stage == "confirm_generate":
            print("DEBUG: Handling 'confirm_generate' stage.")
            if prompt.lower() in ["yes", "y", "ok", "generate", "confirm"]:
                print("DEBUG: User confirmed generation. Checking credentials...")
                creds = get_credentials() 
                if not creds or not creds.valid:
                     bot_response = "Authentication needed. Please use the 'Login with Google' button in the sidebar and complete the authorization steps first."
                     print("DEBUG: Credentials invalid/missing for generation.")
                     trigger_rerun = False # Wait for user to login
                else:
                    print("DEBUG: Credentials valid. Moving to 'generating' stage.")
                    st.session_state.stage = "generating"
                    bot_response = "Okay, generating the Google Doc now..." 
            else:
                print("DEBUG: User did not confirm generation.")
                bot_response = "Okay, I won't generate the document yet. Let me know if you change your mind or type 'yes' to generate."
                # Stay in confirm_generate stage
            print(f"DEBUG: 'confirm_generate' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")


        elif current_stage == "generating":
             print("DEBUG: Handling 'generating' stage.")
             creds = get_credentials() 
             if creds and creds.valid:
                 print("DEBUG: Credentials valid, attempting document creation...")
                 with st.spinner("Creating and populating Google Doc... This may take a moment."):
                      doc_title = create_google_doc(
                          creds,
                          st.session_state.current_quarter,
                          st.session_state.answers
                      )
                 if doc_title:
                      print(f"DEBUG: Document creation successful. Title: {doc_title}")
                      bot_response = report_section_prompts["generation_complete"].format(doc_title)
                      st.session_state.stage = "done" 
                 else:
                      print("ERROR: Document creation failed (create_google_doc returned None).")
                      bot_response = report_section_prompts["error"] + " Failed during document creation. Please check Google permissions or try again."
                      st.session_state.stage = "confirm_generate" 
             else:
                 print("ERROR: Credentials invalid/expired before generation could start.")
                 bot_response = "Google authentication failed or expired. Please log in again via the sidebar before generating."
                 st.session_state.stage = "confirm_generate" 
             trigger_rerun = True 
             print(f"DEBUG: 'generating' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")


        elif current_stage == "done":
            print("DEBUG: Handling 'done' stage.")
            bot_response = "Report generation complete. You can start a new report by telling me the quarter number."
            st.session_state.stage = "start" 
            print(f"DEBUG: 'done' processed. Resetting to 'start'. Bot response: '{bot_response[:50]}...'")

        else: 
             print(f"ERROR: Unknown stage encountered: {current_stage}. Resetting.")
             bot_response = report_section_prompts.get("error", "Sorry, I'm in an unknown state. Let's start over.")
             st.session_state.stage = "start" 
             print(f"DEBUG: Unknown stage handled. Resetting to 'start'. Bot response: '{bot_response[:50]}...'")


    except Exception as e:
         print(f"ERROR: Unexpected exception in chatbot logic (Stage: {current_stage}): {e}")
         print(traceback.format_exc())
         st.error(f"An unexpected error occurred: {e}")
         bot_response = report_section_prompts.get("error", "An unexpected error occurred. Resetting.")
         st.session_state.stage = "start" 


    # Add bot response to history and rerun if needed
    if bot_response:
        st.session_state.messages.append({"role": "assistant", "content": bot_response})
    
    # Rerun decision: Rerun unless explicitly told not to (e.g., waiting for auth)
    if trigger_rerun:
        print("--- Triggering Streamlit Rerun ---")
        st.rerun()
    else:
        print("--- Suppressing Streamlit Rerun (likely waiting for user action) ---")


# --- Initial Bot Prompt ---
if not st.session_state.messages:
     print("--- Adding initial bot prompt ---")
     initial_prompt = report_section_prompts["start"]
     st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
     st.rerun() # Rerun to display the initial message
elif st.session_state.stage == "start" and len(st.session_state.messages) > 0 and st.session_state.messages[-1]["role"] == "user":
     # Handle case where user provided input but stage reset without bot response (e.g. error)
     # Re-prompting might be needed, or check if last message needs processing again?
     # For simplicity, we might rely on the main input loop to handle this on next input.
     # Or add a specific re-prompt if needed.
     pass

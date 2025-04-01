import streamlit as st
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json # Keep json import, might be useful elsewhere, though not for Flow config now
from datetime import datetime
import io

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file'] # Access Docs and create files

# Prepare the client config dictionary directly from secrets
try:
    # Get the AttrDict for the 'web' part
    web_config_attrdict = st.secrets["google_credentials"]["web"]
    # Convert the AttrDict to a standard Python dictionary
    web_config_dict = dict(web_config_attrdict)
    # Construct the full dictionary structure expected by from_client_config
    required_keys = ["client_id", "project_id", "auth_uri", "token_uri", "client_secret"] # Add others if needed (like redirect_uris if specified in secrets)
    if not all(key in web_config_dict for key in required_keys):
        missing = [key for key in required_keys if key not in web_config_dict]
        st.error(f"Google Credentials in Streamlit Secrets are missing keys in the 'web' section: {missing}")
        st.stop()
        
    # This is the dictionary we will pass to the Flow function
    FULL_CLIENT_CONFIG_DICT = {"web": web_config_dict} 
    
except KeyError:
    st.error("Google Credentials section `[google_credentials.web]` not found or incomplete in Streamlit Secrets. Please check configuration.")
    st.stop()
except Exception as e:
    st.error(f"Error processing credentials from secrets: {e}")
    st.stop()

# Determine Redirect URI - Use App URL for deployed apps, localhost for local testing
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
    "quarter_end_date", # Ask this first
    "overall_summary", "progress", "issues_actions", "scope", "time",
    "cost", "exploitation", "risk_management", "project_planning",
    "next_quarter_forecast",
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
    "ready_to_generate": "I have collected information for all sections. Are you ready to generate the Google Doc draft? (Type 'yes' to confirm)",
    "generation_complete": "Done! You can find the draft document '{0}' in your Google Drive.",
    "error": "Sorry, something went wrong. Please try again."
}

# --- Google Authentication ---
def get_credentials():
    """Gets user credentials using OAuth 2.0 flow."""
    # Check if valid credentials already exist in session state
    if 'credentials' in st.session_state and st.session_state.credentials and st.session_state.credentials.valid:
         # Add logic to check if token needs refresh? Google library usually handles this.
         # if st.session_state.credentials.expired and st.session_state.credentials.refresh_token:
         #     st.session_state.credentials.refresh(Request()) # Requires google.auth.transport.requests
         #     st.experimental_rerun()
         return st.session_state.credentials

    # Create Flow instance using the dictionary loaded from secrets
    try:
        flow = Flow.from_client_config(
            FULL_CLIENT_CONFIG_DICT,  # Pass the prepared dictionary
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI_TYPE
        )
    except ValueError as e:
        st.error(f"Error creating OAuth Flow. Check credentials format in Secrets: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error creating OAuth Flow: {e}")
        return None

    # Proceed with the selected OAuth flow type
    if REDIRECT_URI_TYPE == 'urn:ietf:wg:oauth:2.0:oob':
        # Use Out-of-Band flow (user copies code)
        auth_url, _ = flow.authorization_url(prompt='consent')
        st.warning(f"Please go to this URL to authorize the application:\n{auth_url}")
        # Use a unique key for the text input to avoid conflicts
        auth_code = st.text_input("Enter the authorization code here:", key="google_auth_code_input")

        if auth_code:
            try:
                # Attempt to fetch token using the provided code
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials # Store credentials in session state
                st.success("Google authentication successful!")
                # Use st.rerun() instead of st.experimental_rerun() in newer Streamlit versions
                st.rerun() # Rerun to update UI state after getting creds
                return flow.credentials
            except Exception as e:
                st.error(f"Error fetching token with provided code: {e}")
                # Clear potentially invalid credentials if fetching fails
                if 'credentials' in st.session_state:
                    del st.session_state['credentials']
                return None
        else:
            # Still waiting for user to enter the authorization code
            st.info("Waiting for authorization code entry...")
            return None
    else:
        # Placeholder for standard web flow (if implemented later)
        st.error("Standard web auth flow not fully implemented for this example. Using 'oob' flow.")
        return None


# --- Google Docs API Function ---
def create_google_doc(credentials, quarter_number, answers):
    """Creates a new Google Doc with the report content."""
    try:
        service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials) # Need drive service to set title

        title = f"Innovate UK Q{quarter_number} Report - {PROJECT_DETAILS['Project Number']} - Draft {datetime.now().strftime('%Y%m%d_%H%M')}"

        # 1. Create the document
        body = {'title': title}
        doc = service.documents().create(body=body).execute()
        doc_id = doc.get('documentId')

        # 2. Build the full report text
        full_text = f"# Innovate UK Quarterly Report - Q{quarter_number}\n\n"
        full_text += f"**Project:** {PROJECT_DETAILS['Project title']} ({PROJECT_DETAILS['Project Number']})\n"
        full_text += f"**Quarter End Date:** {answers.get('quarter_end_date', 'N/A')}\n\n---\n\n"
        # Iterate through sections in the defined order, skipping the date as it's already included
        for key in report_section_keys:
            if key == "quarter_end_date": continue # Skip adding date again here
            section_title = key.replace('_', ' ').title()
            content = answers.get(key, '*No data entered*')
            full_text += f"## {section_title}\n\n{content}\n\n---\n\n"

        # 3. Prepare the batchUpdate request to insert the text
        # Google Docs API inserts text at index 1 (after title segment)
        requests = [{'insertText': {'location': {'index': 1}, 'text': full_text}}]

        # 4. Execute the batchUpdate
        result = service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        st.success(f"Successfully created and updated Google Doc.")
        return title # Return title for confirmation message

    except HttpError as error:
        st.error(f"An error occurred with Google Docs/Drive API: {error}")
        # Attempt to parse error details if possible
        error_details = getattr(error, 'resp', {}).get('content', '{}')
        try:
             error_json = json.loads(error_details)
             st.json(error_json) # Display detailed error from Google if available
        except:
             st.write(f"Raw error content: {error_details}") # Show raw error if not JSON
        return None
    except Exception as e:
         st.error(f"An unexpected error occurred during document creation: {e}")
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
st.set_page_config(page_title="IUK Grant Bot", layout="wide")
st.title("Innovate UK Grant Reporting Chatbot")
st.write(f"Assisting with: {PROJECT_DETAILS['Project title']}")

# --- Authentication Section (Sidebar) ---
st.sidebar.title("Google Authentication")
# Check credentials validity more robustly
creds = st.session_state.get('credentials')
if creds and creds.valid:
    st.sidebar.success("Authenticated with Google.")
    if st.sidebar.button("Logout Google"):
         st.session_state.credentials = None
         st.rerun()
else:
    st.sidebar.warning("Not authenticated with Google.")
    if st.sidebar.button("Login with Google"):
        # This button click triggers the auth flow display within get_credentials
        # The actual credential setting happens when the auth code is entered
        get_credentials() # Call to display auth URL and input box if needed
        # No need to rerun here, rerun happens inside get_credentials upon success


# --- File Uploader Section (Sidebar) ---
st.sidebar.divider()
st.sidebar.subheader("File Upload (Session Only)")
uploaded_file = st.sidebar.file_uploader(
    "Upload relevant documents when asked",
    type=['pdf', 'docx', 'xlsx', 'png', 'jpg', 'txt'], # Added txt
    key="file_uploader",
    help="Files uploaded here are only available during the current session and are not stored long-term."
)
if uploaded_file:
    # Check size to prevent excessive memory usage in session state
    MAX_FILE_SIZE_MB = 5
    if uploaded_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        st.sidebar.error(f"File size exceeds {MAX_FILE_SIZE_MB}MB limit for session storage.")
    else:
        st.session_state.uploaded_files_info[uploaded_file.name] = {
            "type": uploaded_file.type,
            "size": uploaded_file.size
            # Consider adding content extraction here if needed, store extracted text?
            # e.g., if uploaded_file.type == "text/plain":
            # stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            # st.session_state.uploaded_files_info[uploaded_file.name]['content'] = stringio.read()
        }
        st.sidebar.success(f"File '{uploaded_file.name}' available for this session.")


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
    trigger_rerun = True # Default to rerun unless waiting for input like auth code

    try:
        if current_stage == "start":
            try:
                quarter = int(prompt)
                if 1 <= quarter <= PROJECT_DETAILS['Total Quarters']:
                    st.session_state.current_quarter = quarter
                    st.session_state.answers = {} # Reset answers for new quarter
                    st.session_state.current_section_index = 0 # Start asking sections
                    st.session_state.stage = "ask_section"
                    # Ask first section prompt immediately (which is quarter_end_date)
                    current_key = report_section_keys[st.session_state.current_section_index]
                    bot_response = report_section_prompts.get(current_key, "Please provide details for the first section.")
                else:
                    bot_response = f"Please enter a valid quarter number (1-{PROJECT_DETAILS['Total Quarters']})."
            except ValueError:
                bot_response = "Please enter a number for the quarter."

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
                 # Optional: Add request for file upload contextually
                if next_key in ["time", "risk_management", "cost"]: # Add other relevant sections
                     bot_response += "\n\n" + report_section_prompts["upload_request"]
            else:
                # All sections done
                st.session_state.stage = "confirm_generate"
                bot_response = report_section_prompts["ready_to_generate"]

        elif current_stage == "confirm_generate":
            if prompt.lower() in ["yes", "y", "ok", "generate", "confirm"]:
                # Check authentication status *before* attempting generation
                creds = get_credentials() # Check/refresh credentials
                if not creds or not creds.valid:
                     bot_response = "Please log in with Google first using the sidebar button before generating the document."
                     trigger_rerun = False # Don't rerun if waiting for auth
                else:
                    # Proceed with generation
                    st.session_state.stage = "generating"
                    bot_response = "Okay, generating the Google Doc now..." # Immediate feedback
                    # Generation happens on the rerun triggered after this block
            else:
                bot_response = "Okay, I won't generate the document yet. Let me know if you change your mind."
                # Stay in confirm_generate stage or reset? Resetting might be safer.
                # st.session_state.stage = "start" # Option to reset conversation

        # Separate stage for actual generation to show spinner correctly
        elif current_stage == "generating":
             # This stage is entered on the rerun after user confirms 'yes'
             creds = get_credentials() # Get credentials again just in case
             if creds and creds.valid:
                 with st.spinner("Creating and populating Google Doc..."):
                      doc_title = create_google_doc(
                          creds,
                          st.session_state.current_quarter,
                          st.session_state.answers
                      )
                 if doc_title:
                      bot_response = report_section_prompts["generation_complete"].format(doc_title)
                      st.session_state.stage = "done" # Conversation loop ends or resets
                 else:
                      bot_response = report_section_prompts["error"] + " Failed during document creation."
                      st.session_state.stage = "confirm_generate" # Go back to allow retry
             else:
                 bot_response = "Google authentication issue. Please try logging in again via the sidebar."
                 st.session_state.stage = "confirm_generate" # Go back
             trigger_rerun = True # Ensure UI updates after generation attempt


        elif current_stage == "done":
            # After generation, what next? Reset or wait?
            bot_response = "Report generation complete. You can start a new report by telling me the quarter number, or close the session."
            st.session_state.stage = "start" # Reset for next report

        else: # Default / Error stage
             bot_response = report_section_prompts.get("error", "Sorry, I'm not sure how to proceed from this state.")
             st.session_state.stage = "start" # Reset

    except Exception as e:
         st.error(f"An error occurred in the chatbot logic: {e}")
         bot_response = report_section_prompts.get("error", "An unexpected error occurred.")
         st.session_state.stage = "start" # Reset on error


    # Add bot response to history and rerun if needed
    if bot_response:
        st.session_state.messages.append({"role": "assistant", "content": bot_response})
    if trigger_rerun:
        st.rerun()


# --- Initial Bot Prompt ---
# Add the initial prompt only if the chat history is empty.
if not st.session_state.messages:
     initial_prompt = report_section_prompts["start"]
     st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
     st.rerun() # Rerun to display the initial message

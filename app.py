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
import traceback
# Consider adding PyPDF2 if PDF parsing is attempted later:
# import PyPDF2

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
REDIRECT_URI_TYPE = 'urn:ietf:wg:oauth:2.0:oob'
GRANTI_AUNTY_AVATAR = "https://images.icon-icons.com/3708/PNG/512/girl_female_woman_person_face_people_curly_hair_icon_230020.png" # Replace with your desired URL or local path if added to repo

# --- Load Individual Secret Values ---
# (Same robust loading logic as before)
client_id = None
project_id = None
auth_uri = None
token_uri = None
auth_provider_x509_cert_url = None
client_secret = None
redirect_uris = None

print("--- Attempting to load individual credential values from secrets ---")
try:
    secrets_web = st.secrets.get("google_credentials", {}).get("web", {})
    if not secrets_web: raise ValueError("`[google_credentials.web]` section not found or empty.")
    client_id = secrets_web.get("client_id")
    project_id = secrets_web.get("project_id")
    auth_uri = secrets_web.get("auth_uri")
    token_uri = secrets_web.get("token_uri")
    auth_provider_x509_cert_url = secrets_web.get("auth_provider_x509_cert_url")
    client_secret = secrets_web.get("client_secret")
    redirect_uris = secrets_web.get("redirect_uris")
    required_values = {"client_id": client_id, "project_id": project_id, "auth_uri": auth_uri, "token_uri": token_uri, "client_secret": client_secret}
    missing = [k for k, v in required_values.items() if not v]
    if missing: raise ValueError(f"Required credential values missing from secrets: {missing}")
    if redirect_uris is not None and not isinstance(redirect_uris, list):
         if isinstance(redirect_uris, str): redirect_uris = [redirect_uris]
         else: raise TypeError(f"redirect_uris must be list/str, found {type(redirect_uris)}")
    print("--- Individual credential values loaded successfully ---")
except (KeyError, AttributeError, ValueError, TypeError) as e:
    err_msg = f"Error accessing/validating secrets: {e}. Check TOML format/keys."
    print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
    st.error(err_msg)
    st.stop()
except Exception as e:
    err_msg = f"Unexpected error loading secrets: {e}"
    print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
    st.error(err_msg)
    st.stop()


# --- Constants & Prompts ---
PROJECT_DETAILS = { # (Unchanged)
    "Lead Company Name": "FLOX Limited",
    "Project title": "NetFLOX360 – Bridging Poultry Farm Data with Factory Insights using Artificial Intelligence for Sustainable Growth",
    "Project Number": "10103645",
    "Total Quarters": 4
}
report_section_keys = [ # (Unchanged)
    "quarter_end_date",
    "overall_summary", "progress", "issues_actions", "scope", "time",
    "cost", "exploitation", "risk_management", "project_planning",
    "next_quarter_forecast",
]
report_section_prompts = { # Updated prompts
    "start": "Hello there! I'm Granti Aunty. I can help you draft your Innovate UK Quarterly Report for NetFLOX360. Which reporting quarter (1-{0}) are you working on?",
    "request_grant_app": "Okay, Quarter {0}. To help provide context, please upload your original **Grant Application PDF** using the uploader below. I won't store it long-term, just for this session.",
    "grant_app_received": "Thanks! I've received the Grant Application file for this session. Remember to refer to it!\nNow, what is the **end date** for Quarter {0} (YYYY-MM-DD)?",
    "quarter_end_date": "Got the date! Let's start with the '{0}' section.", # Will be formatted dynamically
    "overall_summary": "Okay, let's draft the **Overall Summary**. Please provide brief points on Scope, Time, Cost, Exploitation, Risk, and PM status. Remember to check your Grant Application for objectives.",
    "progress": "Next, tell me about **Progress**. What were the highlights, key achievements, and overall successes this quarter? How did you address any previous issues?",
    "issues_actions": "Now for **Issues and Actions**. Briefly list any key issues faced this quarter and the actions taken or planned. Do you need any help from the Monitoring Officer?",
    "scope": "Let's discuss **Scope**. Has it remained aligned with the original plan (check your Grant Application)? Any changes, concerns, or deviations? Are technical objectives still on track?",
    "time": "How about **Time**? Which deliverables/milestones were due (check your Project Plan/Gantt)? Were they achieved? If delayed, please explain the reason, impact, and corrective actions.",
     "cost": "Now for the **Cost** summary. Please provide a general statement on costs vs forecast and explain any significant variances (>5-10%) per partner.",
    "exploitation": "Tell me about **Exploitation** activities this quarter (market engagement, IP progress, dissemination, etc.). How does this align with your Exploitation Plan?",
    "risk_management": "What are the updates regarding **Risk Management**? Any new/retired risks, changes in impact/likelihood (check your Risk Register)? What are the biggest risks now?",
    "project_planning": "How has **Project Planning** been? Describe team collaboration, PM challenges, and any improvements made. Has the Gantt chart been updated?",
    "next_quarter_forecast": "Finally, what is the **Updated forecast for next quarter**? Main activities, challenges, and scheduled deliverables?",
    "upload_request": "Need to upload supporting evidence (e.g., Risk Register, Gantt)? Use the uploader in the sidebar. **Note: Files are only available during this session.**",
    "ready_to_generate": "Excellent! I have collected information for all sections for Q{0}. Are you ready for me to generate the Google Doc draft? (Type 'yes' to confirm)",
    "generation_complete": "All done! You can find the draft document titled '{0}' in your Google Drive.",
    "error": "Oh dear, something went wrong. Please try again or check the logs if the issue persists."
}

# --- Google Authentication (Unchanged) ---
def get_credentials():
    print("--- Entering get_credentials function ---")
    if 'credentials' in st.session_state and st.session_state.credentials and st.session_state.credentials.valid:
         print("DEBUG: Valid credentials found in session state.")
         return st.session_state.credentials
    client_config = {"web": {"client_id": client_id,"project_id": project_id,"auth_uri": auth_uri,"token_uri": token_uri,"auth_provider_x509_cert_url": auth_provider_x509_cert_url,"client_secret": client_secret}}
    if redirect_uris is not None: client_config["web"]["redirect_uris"] = redirect_uris
    print("DEBUG: Creating OAuth Flow instance...")
    try:
        flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI_TYPE)
        print("DEBUG: OAuth Flow instance created successfully.")
    except Exception as e:
        err_msg = f"Error creating OAuth Flow: {e}"
        print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
        st.error(err_msg + " Check app logs/secrets.")
        return None
    if REDIRECT_URI_TYPE == 'urn:ietf:wg:oauth:2.0:oob':
        print("DEBUG: Using 'oob' OAuth flow.")
        try: auth_url, _ = flow.authorization_url(prompt='consent')
        except Exception as e: print(f"ERROR: Auth URL generation failed: {e}\n{traceback.format_exc()}"); st.error(f"Error generating auth URL: {e}"); return None
        st.warning(f"**Action Required:**\n1. Go to: [Google Auth Link]({auth_url})\n2. Grant permissions.\n3. Copy the code.\n4. Paste code below.")
        auth_code = st.text_input("Enter authorization code:", key="google_auth_code_input", type="password")
        if auth_code:
            print("DEBUG: Auth code entered. Fetching token...")
            try:
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials
                print("DEBUG: Token fetch success.")
                st.success("Google authentication successful!")
                st.rerun()
                return flow.credentials
            except Exception as e:
                err_msg = f"Error fetching token: {e}"
                print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
                st.error(err_msg + ". Check code/permissions.")
                if 'credentials' in st.session_state: del st.session_state['credentials']
                return None
        else: print("DEBUG: Waiting for auth code."); st.info("Waiting for authorization code."); return None
    else: st.error("'oob' flow required for this setup."); return None

# --- Google Docs API Function (With Added Logging & Checks) ---
def create_google_doc(credentials, quarter_number, answers):
    """Creates a new Google Doc with the report content."""
    print("--- Entering create_google_doc function ---")

    # --- Pre-API Call Checks ---
    if not credentials:
        err_msg = "Credentials object is None when trying to create doc."
        print(f"ERROR: {err_msg}")
        st.error(err_msg)
        return None

    print(f"DEBUG: Type of credentials object passed: {type(credentials)}")

    # Check validity and scopes
    if hasattr(credentials, 'valid'):
        print(f"DEBUG: Credentials valid attribute: {credentials.valid}")
        if not credentials.valid:
             # Check for refresh token which might allow refresh
             if hasattr(credentials, 'has_scopes') and credentials.has_scopes(SCOPES) and hasattr(credentials, 'refresh_token') and credentials.refresh_token:
                  print("WARN: Credentials seem expired but refresh token exists. Attempting refresh implicitly by library...")
                  # The library often handles refresh automatically if refresh token is present & scopes match
                  # We can try forcing a refresh for debugging, requires RequestsCallback transport
                  # try:
                  #      from google.auth.transport.requests import Request
                  #      credentials.refresh(Request())
                  #      print("DEBUG: Manual refresh attempted.")
                  #      if not credentials.valid: raise Exception("Refresh failed.")
                  # except Exception as refresh_err:
                  #      err_msg = f"Credentials expired and refresh failed: {refresh_err}"
                  #      print(f"ERROR: {err_msg}")
                  #      st.error(err_msg + " Please re-authenticate.")
                  #      if 'credentials' in st.session_state: del st.session_state['credentials']
                  #      st.rerun()
                  #      return None

             else:
                  err_msg = "Credentials are not valid and/or refresh token is missing/scopes insufficient for refresh."
                  print(f"ERROR: {err_msg}")
                  st.error(err_msg + " Please re-authenticate.")
                  if 'credentials' in st.session_state: del st.session_state['credentials']
                  st.rerun() # Force rerun to prompt login
                  return None
    else:
        print("WARN: Credentials object does not have 'valid' attribute. Proceeding cautiously.")

    granted_scopes = []
    if hasattr(credentials, 'scopes'):
        granted_scopes = credentials.scopes or []
        print(f"DEBUG: Scopes associated with credentials: {granted_scopes}")
        # Verify required scopes are present
        required_scopes_set = set(SCOPES)
        granted_scopes_set = set(granted_scopes)
        if not required_scopes_set.issubset(granted_scopes_set):
             missing_scopes = required_scopes_set - granted_scopes_set
             err_msg = f"Required scopes missing: {missing_scopes}. Please re-authenticate and ensure ALL permissions ({', '.join(SCOPES)}) are granted."
             print(f"ERROR: {err_msg}")
             st.error(err_msg)
             if 'credentials' in st.session_state: del st.session_state['credentials']
             st.rerun() # Force rerun to prompt login
             return None
        else:
            print("DEBUG: All required scopes appear granted.")
    else:
        print("WARN: Could not read scopes from credentials object. Cannot verify permissions.")
    # --- End Pre-API Call Checks ---

    try:
        print("DEBUG: Building Google Docs and Drive services...")
        # Add cache_discovery=False for debugging if suspecting stale discovery docs
        service_docs = build('docs', 'v1', credentials=credentials, cache_discovery=False)
        service_drive = build('drive', 'v3', credentials=credentials, cache_discovery=False) # Use separate variable
        print("DEBUG: Services built successfully.")

        title = f"Innovate UK Q{quarter_number} Report - {PROJECT_DETAILS['Project Number']} - Draft {datetime.now().strftime('%Y%m%d_%H%M')}"
        print(f"DEBUG: Attempting to create doc with title: {title}")

        # --- Create Document using Drive API first (often more reliable for creation) ---
        file_metadata = {
            'name': title,
            'mimeType': 'application/vnd.google-apps.document'
        }
        print(f"DEBUG: Calling drive.files().create() with metadata: {file_metadata}")
        # Use fields='id' to only request the ID back
        created_file = service_drive.files().create(body=file_metadata, fields='id').execute()
        doc_id = created_file.get('id')

        # doc_body_for_docs_create = {'title': title}
        # print(f"DEBUG: Calling docs.documents().create() with body: {doc_body_for_docs_create}")
        # doc = service_docs.documents().create(body=doc_body_for_docs_create).execute()
        # doc_id = doc.get('documentId')

        if not doc_id:
            err_msg = "Failed to create Google Doc: No document ID returned from Drive API."
            print(f"ERROR: {err_msg}")
            st.error(err_msg)
            return None
        print(f"DEBUG: Google Doc created via Drive API with ID: {doc_id}")

        # --- Now populate the created document using Docs API ---
        print("DEBUG: Building report text content...")
        full_text = f"# Innovate UK Quarterly Report - Q{quarter_number}\n\n"
        full_text += f"**Project:** {PROJECT_DETAILS['Project title']} ({PROJECT_DETAILS['Project Number']})\n"
        full_text += f"**Quarter End Date:** {answers.get('quarter_end_date', 'N/A')}\n\n---\n\n"
        for key in report_section_keys:
            if key == "quarter_end_date": continue
            section_title = key.replace('_', ' ').title()
            content = answers.get(key, "*No data entered for this section.*")
            if st.session_state.current_quarter > 1:
                 prev_q_num = st.session_state.current_quarter - 1
                 prev_answer = st.session_state.get('all_answers', {}).get(prev_q_num, {}).get(key)
                 if prev_answer:
                      # Truncate previous answer reasonably
                      prev_answer_snippet = prev_answer[:200] + ('...' if len(prev_answer) > 200 else '')
                      content += f"\n\n*(Context: Your answer for Q{prev_q_num} was: '{prev_answer_snippet}')*"
            full_text += f"## {section_title}\n\n{content}\n\n---\n\n"
        print(f"DEBUG: Report text built (length: {len(full_text)} chars).")

        print("DEBUG: Preparing batchUpdate request...")
        # Insert text at the beginning of the document body (index 1)
        requests = [{'insertText': {'location': {'index': 1}, 'text': full_text}}]
        print(f"DEBUG: Request body for batchUpdate: {requests}") # Log the request body

        print(f"DEBUG: Executing batchUpdate for doc ID: {doc_id}...")
        result = service_docs.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print(f"DEBUG: batchUpdate executed successfully. Result: {result}") # Log the result
        st.success(f"Successfully created and populated Google Doc.")

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        st.markdown(f"**[Open Generated Document]({doc_url})**", unsafe_allow_html=True)

        return title

    except HttpError as error:
        err_msg = f"Google API Error during document operation: {error}"
        print(f"ERROR: {err_msg}")
        error_details_bytes = getattr(error, 'resp', {}).get('content', b'{}')
        error_details_str = error_details_bytes.decode('utf-8', errors='ignore') # Decode bytes
        print(f"ERROR DETAILS FROM GOOGLE (Decoded): {error_details_str}")
        st.error(err_msg)
        try:
             # Try parsing Google's detailed error message
             error_json = json.loads(error_details_str)
             st.json(error_json) # Display detailed error from Google if available
             google_error_message = error_json.get('error', {}).get('message', 'No specific message found in JSON.')
             st.error(f"Google Error Message: {google_error_message}")
        except Exception as parse_error:
             print(f"Could not parse Google error details as JSON: {parse_error}")
             st.write(f"Raw error content: {error_details_str}") # Show decoded string
        return None
    except Exception as e:
         err_msg = f"Unexpected error during document creation: {e}"
         print(f"ERROR: {err_msg}\n{traceback.format_exc()}")
         st.error(err_msg)
         return None

# --- Initialize Streamlit Session State ---
if 'messages' not in st.session_state: st.session_state.messages = []
if 'stage' not in st.session_state: st.session_state.stage = "start"
if 'current_quarter' not in st.session_state: st.session_state.current_quarter = None
if 'current_section_index' not in st.session_state: st.session_state.current_section_index = 0
# Store all answers per quarter
if 'all_answers' not in st.session_state: st.session_state.all_answers = {}
if 'credentials' not in st.session_state: st.session_state.credentials = None
# Store general uploaded file info (name, type, size) - content maybe too large
if 'uploaded_files_session_info' not in st.session_state: st.session_state.uploaded_files_session_info = {}
# Store grant application specific info (if uploaded)
if 'grant_app_info' not in st.session_state: st.session_state.grant_app_info = None
# Profile Info
if 'user_name' not in st.session_state: st.session_state.user_name = "User"
if 'profile_pic' not in st.session_state: st.session_state.profile_pic = None


# --- App Layout ---
st.set_page_config(page_title="Granti Aunty", layout="centered")
st.title("Granti Aunty")
st.write(f"Your Innovate UK Reporting Assistant for: **{PROJECT_DETAILS['Project title']}**")
st.caption("Let's draft your quarterly report together!")

# --- Sidebar ---
st.sidebar.title("Settings & Info")

# Profile Section
st.sidebar.subheader("Your Profile")
new_name = st.sidebar.text_input("Your Name:", value=st.session_state.user_name, key="user_name_input")
if new_name != st.session_state.user_name:
    st.session_state.user_name = new_name
    st.rerun() # Update name display immediately

profile_pic_file = st.sidebar.file_uploader("Upload Profile Picture:", type=['png', 'jpg', 'jpeg'], key="profile_pic_uploader")
if profile_pic_file:
    st.session_state.profile_pic = profile_pic_file.getvalue() # Store image bytes
    # No rerun needed here, image will display on next natural rerun

if st.session_state.profile_pic:
    st.sidebar.image(st.session_state.profile_pic, caption=f"{st.session_state.user_name}'s Profile Pic", width=100)
else:
    st.sidebar.text("(No profile picture uploaded)")


# Google Auth Section
st.sidebar.divider()
st.sidebar.subheader("Google Authentication")
creds = st.session_state.get('credentials')
if creds and creds.valid:
    st.sidebar.success("Authenticated with Google.")
    if st.sidebar.button("Logout Google"):
         st.session_state.credentials = None
         st.rerun()
else:
    st.sidebar.warning("Not authenticated with Google (needed to create Google Doc).")
    if st.sidebar.button("Login with Google"):
        get_credentials() # Call to potentially display the auth prompt

# General File Uploader Section
st.sidebar.divider()
st.sidebar.subheader("Upload Supporting Files")
support_file = st.sidebar.file_uploader(
    "Upload Risk Register, Gantt, Evidence etc.",
    type=['pdf', 'docx', 'xlsx', 'png', 'jpg', 'txt'],
    key="support_file_uploader",
    help="Files uploaded here are only available during the current session."
)
if support_file:
    MAX_FILE_SIZE_MB = 5
    if support_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        st.sidebar.error(f"File size exceeds {MAX_FILE_SIZE_MB}MB limit.")
    else:
        # Store info, maybe overwrite if same name uploaded?
        st.session_state.uploaded_files_session_info[support_file.name] = {
            "type": support_file.type, "size": support_file.size
        }
        st.sidebar.success(f"File '{support_file.name}' available for session.")


# --- Display Chat History ---
chat_container = st.container()
with chat_container:
    for message in st.session_state.messages:
        role = message["role"]
        avatar_icon = st.session_state.profile_pic if role == "user" else GRANTI_AUNTY_AVATAR
        with st.chat_message(role, avatar=avatar_icon):
            st.markdown(message["content"])

# --- Handle Grant App Upload within Chat ---
grant_app_uploader_key = "grant_app_main_uploader"
if st.session_state.stage == "request_grant_app":
     grant_app_file = st.file_uploader(
          "Upload Grant Application PDF",
          type=['pdf'],
          key=grant_app_uploader_key
     )
     if grant_app_file:
          # Process Grant App Upload
          print(f"DEBUG: Grant Application PDF uploaded: {grant_app_file.name}")
          st.session_state.grant_app_info = {
               "name": grant_app_file.name,
               "size": grant_app_file.size,
               "type": grant_app_file.type
               # We could store bytes or extracted text here if needed & feasible
          }
          st.session_state.stage = "ask_section" # Move to next stage (asking for end date)
          st.session_state.current_section_index = 0 # Reset section index for first question
          bot_response = report_section_prompts["grant_app_received"].format(st.session_state.current_quarter)
          st.session_state.messages.append({"role": "assistant", "content": bot_response})
          # Clear the specific uploader after successful upload using rerun
          st.rerun() # Rerun to move past the uploader and show the next prompt


# --- Handle General Chat Input ---
if prompt := st.chat_input("Your answer or command...", key="chat_input_main"):
    print(f"DEBUG: User input received: '{prompt[:50]}...'")
    st.session_state.messages.append({"role": "user", "content": prompt})

    current_stage = st.session_state.stage
    print(f"DEBUG: Current stage: {current_stage}")
    bot_response = ""
    trigger_rerun = True

    try:
        # --- Bot Logic Stages ---
        if current_stage == "start":
            print("DEBUG: Handling 'start' stage.")
            # Use Selectbox for Quarter Selection now - This logic needs rethink
            # The prompt now happens *before* selection. Selection widget needed.
            # Let's adjust: The start prompt is just text. User selection happens via widget.
            # We need a way to *trigger* the process after selection. Maybe a button?
            # For now, let's assume the first user text input *is* the quarter number.

            try:
                 quarter_options = list(range(1, PROJECT_DETAILS['Total Quarters'] + 1))
                 # This selection should ideally happen via a widget before chat starts,
                 # but integrating into the flow:
                 try_quarter = int(prompt)
                 if try_quarter in quarter_options:
                      st.session_state.current_quarter = try_quarter
                      st.session_state.stage = "request_grant_app" # NEW Stage
                      bot_response = report_section_prompts["request_grant_app"].format(st.session_state.current_quarter)
                 else:
                      bot_response = f"Please enter a valid quarter number {quarter_options} to begin."
            except ValueError:
                 bot_response = f"Please tell me which quarter number {quarter_options} you want to report on."
            print(f"DEBUG: 'start' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")


        elif current_stage == "request_grant_app":
             # This stage primarily waits for the file uploader callback above.
             # If user types instead of uploading:
             bot_response = "Please use the file uploader that appeared above to upload your Grant Application PDF."
             trigger_rerun = False # Don't rerun, wait for uploader

        elif current_stage == "ask_section":
            print(f"DEBUG: Handling 'ask_section'. Current index: {st.session_state.current_section_index}")
            last_section_index = st.session_state.current_section_index
            last_key = report_section_keys[last_section_index]
            print(f"DEBUG: Saving answer for section: '{last_key}'")

            # Store answer in the new structure
            if st.session_state.current_quarter not in st.session_state.all_answers:
                 st.session_state.all_answers[st.session_state.current_quarter] = {}
            st.session_state.all_answers[st.session_state.current_quarter][last_key] = prompt

            # Move to next section
            st.session_state.current_section_index += 1

            if st.session_state.current_section_index < len(report_section_keys):
                 next_key = report_section_keys[st.session_state.current_section_index]
                 print(f"DEBUG: Asking for next section: '{next_key}'")
                 base_prompt = report_section_prompts.get(next_key, "Please provide details for the next section.")
                 
                 # Add context from previous quarter if applicable
                 context_str = ""
                 if st.session_state.current_quarter > 1:
                      prev_q_num = st.session_state.current_quarter - 1
                      prev_answer = st.session_state.get('all_answers', {}).get(prev_q_num, {}).get(next_key)
                      if prev_answer:
                           context_str = f"\n\n*(For context, last quarter (Q{prev_q_num}) you wrote: '{prev_answer[:150]}...')*" # Show more context

                 # Add reminder about grant app
                 grant_app_context_str = ""
                 if next_key in ["scope", "time", "overall_summary"]: # Sections likely related to original app
                      if st.session_state.grant_app_info:
                           grant_app_context_str = f"\n*(Remember to consult your uploaded grant application: '{st.session_state.grant_app_info['name']}')*"
                      else:
                           grant_app_context_str = "\n*(You might want to refer to your original grant application.)*"


                 bot_response = base_prompt + context_str + grant_app_context_str

                 # Add upload reminder
                 if next_key in ["time", "risk_management", "cost"]:
                      bot_response += "\n\n" + report_section_prompts["upload_request"]
            else:
                 print("DEBUG: All sections collected. Moving to 'confirm_generate'.")
                 st.session_state.stage = "confirm_generate"
                 bot_response = report_section_prompts["ready_to_generate"].format(st.session_state.current_quarter)
            print(f"DEBUG: 'ask_section' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")

        # --- Stages confirm_generate, generating, done remain largely the same ---
        # --- Need to update create_google_doc to use st.session_state.all_answers ---
        elif current_stage == "confirm_generate": # (Logic Unchanged)
            print("DEBUG: Handling 'confirm_generate' stage.")
            if prompt.lower() in ["yes", "y", "ok", "generate", "confirm"]:
                print("DEBUG: User confirmed generation. Checking credentials...")
                creds = get_credentials()
                if not creds or not creds.valid:
                     bot_response = "Authentication needed. Please use the 'Login with Google' button in the sidebar and complete the authorization steps first."
                     print("DEBUG: Credentials invalid/missing for generation.")
                     trigger_rerun = False
                else:
                    print("DEBUG: Credentials valid. Moving to 'generating' stage.")
                    st.session_state.stage = "generating"
                    bot_response = "Okay, generating the Google Doc now..."
            else:
                print("DEBUG: User did not confirm generation.")
                bot_response = "Okay, I won't generate the document yet. Let me know if you change your mind or type 'yes' to generate."
            print(f"DEBUG: 'confirm_generate' processed. Next stage: {st.session_state.stage}. Bot response: '{bot_response[:50]}...'")


        elif current_stage == "generating": # (Updated create_google_doc call)
             print("DEBUG: Handling 'generating' stage.")
             creds = get_credentials()
             if creds and creds.valid:
                 print("DEBUG: Credentials valid, attempting document creation...")
                 # Get answers for the current quarter from the new structure
                 current_answers = st.session_state.all_answers.get(st.session_state.current_quarter, {})
                 with st.spinner("Creating and populating Google Doc... This may take a moment."):
                      doc_title = create_google_doc( # Pass current_answers
                          creds,
                          st.session_state.current_quarter,
                          current_answers
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


        elif current_stage == "done": # (Logic Unchanged)
            print("DEBUG: Handling 'done' stage.")
            bot_response = "Report generation complete. You can start a new report by telling me the quarter number."
            st.session_state.stage = "start"
            print(f"DEBUG: 'done' processed. Resetting to 'start'. Bot response: '{bot_response[:50]}...'")

        else: # Default / Error stage (Logic Unchanged)
             print(f"ERROR: Unknown stage encountered: {current_stage}. Resetting.")
             bot_response = report_section_prompts.get("error", "Sorry, I'm in an unknown state. Let's start over.")
             st.session_state.stage = "start"
             print(f"DEBUG: Unknown stage handled. Resetting to 'start'. Bot response: '{bot_response[:50]}...'")


    except Exception as e: # General Error Handling (Logic Unchanged)
         print(f"ERROR: Unexpected exception in chatbot logic (Stage: {current_stage}): {e}")
         print(traceback.format_exc())
         st.error(f"An unexpected error occurred: {e}")
         bot_response = report_section_prompts.get("error", "An unexpected error occurred. Resetting.")
         st.session_state.stage = "start"


    if bot_response:
        st.session_state.messages.append({"role": "assistant", "content": bot_response})

    if trigger_rerun:
        print("--- Triggering Streamlit Rerun ---")
        st.rerun()
    else:
        print("--- Suppressing Streamlit Rerun (likely waiting for user action) ---")


# --- Initial Bot Prompt ---
# Add the initial prompt only if the chat history is empty.
if not st.session_state.messages:
     print("--- Adding initial bot prompt ---")
     initial_prompt = report_section_prompts["start"]
     st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
     st.rerun() # Rerun to display the initial message

# --- Quarter Selection Widget (Alternative Approach) ---
# This widget approach conflicts slightly with the pure chat flow initiated above.
# You would typically have the user select the quarter *before* starting the chat input loop.
# Example - place this near the top if you prefer widget selection:
# quarter_options = list(range(1, PROJECT_DETAILS['Total Quarters'] + 1))
# selected_q = st.selectbox("Select Reporting Quarter:", options=quarter_options, index=None, placeholder="Choose quarter...")
# if selected_q and st.button("Start Report for Q{selected_q}"):
#      st.session_state.current_quarter = selected_q
#      st.session_state.stage = "request_grant_app"
#      # Add initial bot message for grant app request...
#      st.rerun()
# This requires rethinking the 'start' stage logic in the chat input handler.
# The current code assumes the *first text input* is the quarter number.

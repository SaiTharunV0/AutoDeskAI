# AutoDeskAI

AutoDeskAI is an interactive internal IT support assistant powered by Gemini. It classifies employee requests into structured IT workflows and asks for clarification when required information is missing.

## Requirements

- Python 3.11 or newer
- A Gemini API key

## Setup

From this directory, create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create the local environment file and add your API key:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```text
GEMINI_API_KEY=your_gemini_api_key_here
```

Never commit `.env` or share the API key. It is excluded by `.gitignore`.

## Run

```powershell
.\venv\Scripts\python.exe agent.py
```

Enter `exit` or `quit` to stop the agent.

The agent remembers recent turns in the current session. For example:

```text
Employee: I need access
AI Agent: Which application do you need access to?
Employee: Excel
AI Agent: ACCESS_REQUEST for Excel
```

## Supported Intents

- `PASSWORD_CHANGE`
- `PASSWORD_RESET`
- `SOFTWARE_INSTALL`
- `ACCESS_REQUEST`
- `CHAT`
- `CLARIFICATION`

Access and installation requests require explicit action wording. For example, `I want DNR` is clarified, while `I need access to DNR` is classified as an access request.

## Tests

Run the tests with:

```powershell
.\venv\Scripts\python.exe -m unittest test.py -v
```

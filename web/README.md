# Local Web Preview

Install the project dependencies in the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the local web interface from the project root:

```powershell
.\.venv\Scripts\python.exe -m web.app
```

Open http://127.0.0.1:5055. The server binds to loopback only. Uploaded spreadsheets and generated files stay in a temporary folder on this computer; the existing `src.main` automation performs the calculations unchanged.

## Render Test Deployment

Render is the intended host for a first online test: the automation runs for several minutes and needs a persistent Python process. Vercel's serverless request lifecycle is not a good fit for the current long-running subprocess workflow.

1. Push the app code and `render.yaml` to a GitHub branch. Do not add spreadsheets, logs, `.venv`, generated output, or local workbook paths.
2. In Render, choose **New > Blueprint** and connect the GitHub repository and branch.
3. Review the `aprovadores-cc` web service from `render.yaml` and create it.
4. In the service's **Environment** settings, set `WEB_USERNAME` and `WEB_PASSWORD` to unique credentials. Render will request values for variables marked `sync: false`. Do not put credentials in Git or chat.
5. Wait for the deployment, open the `onrender.com` URL, and sign in when the browser asks. Start with non-sensitive test workbooks.

The deployment uses one web instance because job state and downloads are held in memory and temporary disk. Restarting or redeploying clears active job state and generated files. This prototype has no durable job history, automatic cleanup policy, or organization SSO. Basic authentication is a test gate, not approval to process employee data in a public cloud. Confirm the organization's data-protection requirements before uploading real SAP/RH files.

The local server remains at http://127.0.0.1:5055 and does not require credentials unless `APP_ENV=production` is set.

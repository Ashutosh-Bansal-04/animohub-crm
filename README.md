# Animohub outreach CRM (team view)

A read-only page for the team: funnel summary, every lead by stage, held replies, notifications and meetings for the video lead magnet campaigns.

A GitHub Action pulls fresh data every 15 minutes, encrypts it with the team passcode and publishes the page. No prospect data is stored in this repo in readable form.

## One-time setup

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions → New repository secret.** Add:

| Secret | Needed | What it is |
|---|---|---|
| `CRM_PASSCODE` | yes | The passcode the team types to open the CRM. Use 16 or more characters. |
| `MAKE_API_TOKEN` | yes | Make → Profile → API access → Add token, scope `datastores:read`. |
| `MANYREACH_API_KEY` | yes | Your main ManyReach (organisation) API key. The job also reads every workspace under it, Everly included. |
| `MANYREACH_API_KEY_2` | no | Only needed for a workspace the main key cannot reach. |
| `CAL_API_KEY` | no | cal.com → Settings → Developer → API keys. Turns on the Meetings tab. |

3. **Actions → Update CRM → Run workflow.** When it finishes, the page address is shown on the run and under Settings → Pages.

## Day to day

- The page reloads its data every 5 minutes; the job refreshes it about every 15 (GitHub can run scheduled jobs late).
- To change the passcode, change the `CRM_PASSCODE` secret and run the workflow.
- A campaign is picked up automatically when its ManyReach name contains "Video lead magnet".
- GitHub pauses scheduled jobs in a repo with no commits for 60 days. If the page stops updating, open Actions and re-enable the workflow.
- If a source fails, the page shows which one at the top; the run log under Actions has the detail.

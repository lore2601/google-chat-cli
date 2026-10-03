# Setting up Google Cloud for gchat

`gchat` calls the Google Chat API **as you** (OAuth user authentication). Google requires a Cloud project that owns the OAuth client and has the Chat API enabled. You do this once per person or organisation, and colleagues can share one project.

> In a Google Workspace organisation, your admin may need to allow the app or create the project for you. Personal `@gmail.com` accounts can use Google Chat but have limited API access.

## 1. Create or select a project

Open <https://console.cloud.google.com/projectcreate> and create a project, for example `gchat-cli`.

## 2. Enable the Google Chat API

Open <https://console.cloud.google.com/apis/library/chat.googleapis.com> and click **Enable**.

## 3. Configure the Chat app

Every Chat API call, including calls made with user credentials, needs a configured Chat app in the project. Without one you get `Google Chat app not found`.

1. Go to **APIs & Services → Google Chat API → Configuration**: <https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat>
2. Fill in **App name** (e.g. `gchat CLI`), **Avatar URL** (any HTTPS image) and **Description**.
3. Under *Interactive features* you can **disable** interactivity, because the CLI does not receive events.
4. Save.

## 4. Configure the OAuth consent screen

<https://console.cloud.google.com/auth/branding>

- **User type: Internal** if you are in a Workspace organisation. Only your organisation can use it, and no Google verification is needed.
- **External** otherwise. While in *Testing* mode, add yourself as a test user. Refresh tokens then **expire after 7 days**, so you must run `gchat auth login` again. Publishing the app removes that limit, but sensitive scopes may require Google verification.

Under **Data access** you may add the Chat scopes you plan to use. This step is optional for Internal apps.

## 5. Create the OAuth client

<https://console.cloud.google.com/auth/clients> → **Create client**

- **Application type: Desktop app**
- Name: `gchat`

Download the JSON file. No redirect URI needs to be configured: `gchat` uses a temporary `http://localhost:<port>` callback, which Desktop clients allow automatically.

## 6. Log in

```bash
gchat auth login --client-secrets ~/Downloads/client_secret_XXXX.apps.googleusercontent.com.json
```

The file is copied to `~/.config/gchat/client_secret.json` with `0600` permissions, so later logins do not need the flag. A browser opens: pick your account and approve the scopes.

Choose the permissions you grant with a preset:

| Preset | Scopes | Use it for |
|---|---|---|
| `readonly` | `chat.spaces.readonly`, `chat.messages.readonly`, `chat.memberships.readonly`, `chat.messages.reactions.readonly`, `chat.users.readstate.readonly` | Agents that only summarise or search |
| `default` | `chat.spaces.readonly`, `chat.messages`, `chat.memberships.readonly`, `chat.messages.reactions`, `chat.users.readstate` | Reading and posting |
| `full` | `chat.spaces`, `chat.messages`, `chat.memberships`, `chat.messages.reactions`, `chat.users.readstate` | Also creating spaces and managing members |

```bash
gchat auth login --scopes readonly
gchat auth login --scope chat.spaces.create      # add individual scopes
```

### Machines without a browser (SSH, containers)

```bash
gchat auth login --no-browser --port 8765
```

Open the printed URL on your laptop after forwarding the port (`ssh -L 8765:localhost:8765 host`). You can also log in on a machine with a browser and copy `~/.config/gchat/token.json` over. Treat that file like a password. Alternatively, point `GCHAT_CREDENTIALS_FILE` at it.

### Sharing the OAuth client with your team

A Desktop client ID and secret are not truly secret: Google documents that installed apps cannot keep them confidential. They identify the app, not the user, so you can distribute them to colleagues. Each person still logs in with their own account and gets their own token. Inline variables also work:

```bash
export GCHAT_CLIENT_ID=1234-abc.apps.googleusercontent.com
export GCHAT_CLIENT_SECRET=GOCSPX-...
gchat auth login
```

## Troubleshooting

| Error | Fix |
|---|---|
| `Google Chat app not found` | Complete step 3 (Chat app configuration). |
| `Google Chat API has not been used in project …` | Enable the API (step 2); the error includes an `enableUrl`. |
| `insufficient authentication scopes` | `gchat auth login --scopes full` (or the preset that includes the scope). |
| `invalid_grant` / `Token has been expired or revoked` | `gchat auth login` again. In Testing mode this happens every 7 days. |
| `Access blocked: app not approved` | Your Workspace admin must trust the OAuth client (Admin console → Security → API controls). |

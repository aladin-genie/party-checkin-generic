# Deploying Party Check-In Generic

## 1. Supabase

1. Open https://supabase.com and sign in.
2. Create/open project `party-checkin-generic`.
3. Go to **Project Settings → Database → Connection string → URI**.
4. Copy the **Pooler** connection string:
   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```
5. Paste it into Streamlit secrets (next section). Tables are created automatically when the app
   first runs.

## 2. Streamlit Cloud

1. Go to https://share.streamlit.io/ and sign in with `yvh1225@gmail.com`.
2. Click **New app** → select the `party-checkin-generic` repo → set main file to
   `streamlit_app.py`.
3. **Advanced settings** → set Python version to **3.12**.
4. **Secrets** → paste the contents of `.streamlit/secrets.toml.example` with real values:
   - `DATABASE_URL` = Supabase Pooler string
   - `ADMIN_PASSWORD` = strong password
   - `ZELLE_INFO` = `dfwygana@gmail.com`
   - `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_DEFAULT_SENDER` = Gmail SMTP credentials
     (or leave `MAIL_USERNAME` blank to disable email during testing)
   - `APP_URL` = the deployed Streamlit URL, e.g. `https://party-checkin-generic.streamlit.app`
5. Deploy.

## 3. Post-Deploy Checklist

- [ ] Open the app and confirm no "temporary local database" warning.
- [ ] Confirm the registration page shows pricing: $50 (1–25), $25 (26–75), $10 (76+).
- [ ] Confirm Zelle info shows `dfwygana@gmail.com`.
- [ ] Log in to Admin with the configured password.
- [ ] Register a test guest and verify the QR code appears.
- [ ] Download CSV backup, then reset test data before the real event.

## 4. Before the Real Event

- Update `config.py` with the real event name, date, venue, theme, photos, and sponsors.
- Add the real flyer to `assets/flyer.jpg`.
- Add real photos to `assets/photos/` and list them in `config.PHOTOS`.
- Add real sponsor logos to `assets/sponsors/` and list them in `config.SPONSORS`.
- Update `EVENT_TIMEZONE` in `config.py` if the venue is not in America/Chicago.
- Re-deploy.

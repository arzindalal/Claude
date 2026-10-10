# Family Board

**Live at https://family-board-4d06d.web.app** (Firebase project `family-board-4d06d`). To redeploy after changes, run `firebase deploy` from this folder.

A shared weekly board for chores, errands, and events. Phones sync in real time, and a kiosk view works on a wall tablet. It runs on Firebase's free Spark plan.

## Features
Modeled on the Skylight Calendar feature set.

- **Calendar** with Week, Month, and Schedule views, a forecast on each day, and family countdowns.
- **Events and chores**: add for one or several people at once (each gets their own copy), with times, repeats (daily, weekdays, chosen days), and star values. Tap any card to edit or delete it.
- **Google Calendar sync** per person (read-only, see below).
- **Chore chart** (Chores tab): one column per person with a progress ring, and a big celebration when someone finishes everything.
- **Routines**: morning, afternoon, and evening habit steps, shown for the current time of day.
- **Rewards**: stars per chore, weekly leaderboard with streaks, a family goal, and a reward shop where kids spend saved stars.
- **Meal plan**: breakfast, lunch, dinner, and snack for each day, plus family favorites that pop up as suggestions.
- **Scan a shopping list**: take a photo of a list or whiteboard and the text is read on the phone (Tesseract, served from this site; nothing is uploaded), or paste several lines into a store box. A review screen lets you fix mistakes and pick the store. Printed or neat writing works best.
- **Lists**: groceries split into Costco, Indian store, and grocery store sections with checkboxes for shopping (tap a store to see only its list), plus any number of custom color-coded lists.
- **Weather** for your city (Open-Meteo, free, no key).
- **Wall display** (`?kiosk=1`): fully interactive, keeps the screen awake, returns to the chore chart after 3 idle minutes, photo screensaver, and night-time sleep mode.
- **Reminders** on each device: a notification when a chore or event with a time is due (at the time, or 10/30/60 minutes before). They work while the board is open or recently used; on iPhone and iPad the board must be added to the Home Screen first.
- **Parent PIN** to keep kids out of settings and the reward shop (a kid lock, not real security).
- Live sync between all devices, dark mode, confetti, and "Add to Home Screen" support.

Not included: Skylight's AI assistant (Sidekick / Magic Import), which needs a paid AI service and a server, and licensed character screensavers.

## One-time Firebase setup (about 10 minutes)

1. **Create a project.** Go to https://console.firebase.google.com, click *Add project*, and name it (for example, `family-board`). Google Analytics is optional.
2. **Add a web app.** In *Project settings → Your apps*, click the `</>` icon. Copy the config values into `firebase-config.js`.
3. **Create Firestore.** *Build → Firestore Database → Create database.* Choose a region near you, and start in production mode.
4. **Add the security rules.** In Firestore → *Rules*, paste the contents of `firestore.rules`, then *Publish*.
5. **Hosting (free).** Install the CLI once: `npm install -g firebase-tools`. Then from this folder run:
   ```
   firebase login
   firebase init hosting     # public directory: . , single-page app: No, overwrite index.html: No
   firebase deploy --only hosting
   ```
   The CLI prints your site URL, for example `https://your-project.web.app`.

## Google Calendar (optional, about 5 minutes, free)

Each family member connects their own Google Calendar from their own phone with Google's sign-in window. The board gets **read-only** access, never sees passwords, and stores no Google sign-in tokens in the database. Imported events are copied to the family board so every device, including the wall display, shows them.

**How syncing works (no server):** a person's calendar updates when they open the board on their phone. If their Google access is still fresh (about an hour), it syncs automatically; otherwise they tap 🔄 once. Fully automatic background sync would need a small server (Cloud Functions on Firebase's pay-as-you-go plan).

One-time setup in [Google Cloud Console](https://console.cloud.google.com/), with the project **family-board-4d06d** selected:
1. **Turn on the API:** *APIs & Services → Library →* search "Google Calendar API" → *Enable*.
2. **Consent screen:** *Google Auth Platform → Branding*: app name "Family Board", your email as support and developer contact. *Audience*: External, Testing. Under *Test users*, add the Gmail address of every family member who will connect a calendar (up to 100).
3. **Client ID:** *Google Auth Platform → Clients → Create client →* Web application. Under *Authorized JavaScript origins* add:
   - `https://family-board-4d06d.web.app`
   - `https://family-board-4d06d.firebaseapp.com`
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`) into `GOOGLE_CLIENT_ID` in `firebase-config.js`, then `firebase deploy --only hosting`.

When connecting, Google shows "Google hasn't verified this app". That's expected for a private family app in Testing mode: tap *Continue*. Removing that screen requires Google's app verification.

To connect: ⚙️ → Google Calendar → "I'm Mom: connect" → pick which calendars to show. Everything from those calendars is visible to anyone with the family link, so leave private calendars unticked.

## Using it
1. Open the site and tap **Create a new family**.
2. Tap **Copy share link** and send it to family members. Each person opens it once on their phone.
3. Add members (for example, *Mom, Dad, Sam*) in the top panel.
4. On a wall tablet, open **Copy kiosk link** and leave it in a browser tab in full screen.

## Security notes
- Anyone with the share link can view and edit that family's board. Treat the link like a password.
- There is no sign-in, so there are no accounts or passwords to manage.
- The rules in `firestore.rules` let anyone read or change a family's board if they know its exact family ID, and block listing all families. Because family IDs are long and random, guessing one is impractical, but a leaked link gives full access.
- Do not put passwords, medical data, or other sensitive information on the board.

## Limits on the free plan
- Spark plan Firestore: about 50,000 reads and 20,000 writes per day, and 1 GiB of storage. A family board uses a tiny fraction of that.
- Hosting: 10 GB storage and 360 MB/day transfer. Also more than enough.

## Files
- `index.html`, `styles.css`, `app.js`: the app.
- `firebase-config.js`: your Firebase keys.
- `firestore.rules`: database access rules.
- `README.md`: this file.

## Not built yet
- Automatic background Google Calendar sync (needs a server; today each person's phone syncs their calendar).
- AI features like Skylight's Sidekick (turning school emails or flyer photos into events).
- Outlook / iCloud calendar sync.
- Per-person accounts, and reminders that arrive when the app is fully closed (needs Firebase Cloud Messaging and a scheduled function on the pay-as-you-go plan).

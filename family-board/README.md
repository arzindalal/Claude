# Family Board

A shared weekly board for chores, errands, and events. Phones sync in real time, and a kiosk view works on a wall tablet. It runs on Firebase's free Spark plan.

## Features
- Seven-day board, starting today.
- Tasks tagged by family member, with a color for each person.
- Anyone can check off or add tasks from their own phone.
- **Kiosk mode** (`?kiosk=1`): read-only, large text, updates live, no sign-in screens.
- Share link: send it to family members to join the same board.

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
- `index.html`: the whole app (HTML, CSS, JavaScript).
- `firebase-config.js`: your Firebase keys.
- `firestore.rules`: database access rules.
- `README.md`: this file.

## Not built yet
- Recurring chores (for example, "trash every Tuesday").
- Points or streaks.
- Per-person accounts and permissions.
- Notifications.

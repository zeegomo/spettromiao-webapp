# spettromiao Webapp

Mobile webapp for the spettromiao DIY Raman spectrometer. This is the frontend that runs in your browser and communicates with the Raspberry Pi API server.

## Architecture

The app is served directly from GitHub Pages and uses **Local Network Access (LNA)** to communicate with the Pi:

```
┌─────────────────────────────────────────────────────────────────┐
│                        HOW IT WORKS                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   1. User connects phone to Pi's WiFi (spettromiao)             │
│                                                                 │
│   2. Opens your GitHub Pages URL in browser                     │
│      └── https://yourusername.github.io/kat-webapp              │
│                                                                 │
│   3. App served from GitHub (HTTPS) communicates with Pi        │
│      └── Uses Local Network Access to reach https://192.168.4.1 │
│                                                                 │
│   4. Browser prompts to allow private network access            │
│      └── User grants permission once                            │
│                                                                 │
│   5. App makes API calls to Pi on local network                 │
│                                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- Updates automatically from GitHub (no Pi deployment needed)
- Works in modern browsers with LNA support (Chrome, Edge, Safari)
- Secure HTTPS connection to both GitHub and Pi
- Simple setup - just enable GitHub Pages

## Setup

### 1. Deploy to GitHub Pages

```bash
cd kat-webapp
git init
git add .
git commit -m "Initial commit"
gh repo create kat-webapp --public --source=. --push
```

Then enable GitHub Pages:
1. Go to repository Settings > Pages
2. Source: Deploy from branch
3. Branch: `main` / `root`
4. Save

Your webapp will be at: `https://yourusername.github.io/kat-webapp`

### 2. Configure the Pi

Ensure your Raspberry Pi:
- Creates a WiFi network named `spettromiao`
- Runs an HTTPS API server on `https://192.168.4.1`
- Has a valid SSL certificate (self-signed is OK, but users must accept it once)

The webapp automatically detects if it's served from GitHub Pages and uses Local Network Access to communicate with the Pi.

### 3. Using the App

1. Connect your phone to the Pi's WiFi network (`spettromiao`)
2. Open your GitHub Pages URL: `https://yourusername.github.io/kat-webapp`
3. First time: Browser will prompt to allow access to devices on local network
4. Grant permission - this allows the app to communicate with the Pi
5. Accept the Pi's SSL certificate if prompted
6. Start using the app!

**Note:** Local Network Access is supported in:
- Chrome/Edge (Android & Desktop)
- Safari (iOS 17+)
- Other Chromium-based browsers

## Updating the Webapp

1. Make changes to files
2. Bump version in `version.txt` (e.g., `1.0.0` → `1.0.1`)
3. Commit and push to GitHub

```bash
echo "1.0.1" > version.txt
git add .
git commit -m "Update webapp"
git push
```

GitHub Pages will automatically deploy the updates. Users will get the new version on their next visit (or after a refresh).

## File Structure

```
kat-webapp/
├── index.html          # Main app page
├── manifest.json       # PWA manifest
├── sw.js               # Service worker
├── version.txt         # Version for cache busting
├── css/
│   └── style.css       # Styles
├── js/
│   ├── app.js          # Main app logic (includes LNA detection)
│   ├── db.js           # IndexedDB storage
│   ├── identifier.js   # Spectrum identification
│   └── sync.js         # CouchDB sync
├── data/
│   └── library.json    # Reference spectra library
└── icons/              # PWA icons
```

## Development

### Testing Locally

```bash
# Serve the app locally
python -m http.server 8000
# Open http://localhost:8000
```

When running on localhost, the app automatically uses relative API URLs (same origin), so it won't attempt to use Local Network Access.

### Testing with GitHub Pages

You can test the full LNA flow by:
1. Deploying to GitHub Pages
2. Connecting to the Pi's WiFi
3. Opening your GitHub Pages URL
4. Granting LNA permission when prompted

For UI development without the Pi, you can still access GitHub Pages, but API calls will fail gracefully.

## Pi Connectivity

The app automatically detects whether it needs Local Network Access based on where it's served from:
- When served from GitHub Pages: Uses LNA to communicate with `https://192.168.4.1`
- When served from localhost/Pi: Uses relative URLs (same origin)

The app shows a warning banner when the Pi is not reachable:
- Checks connectivity every 2 seconds when disconnected
- Checks every 10 seconds when connected (battery friendly)
- Navigation to Step 2 (Calibration) is blocked until connected

## Features

- **Wizard-style interface** for field testing
- **Local Network Access** for Pi communication from GitHub Pages
- **Offline-capable** with service worker caching
- **Local data storage** using IndexedDB
- **Optional sync** to CouchDB server
- **Browser-based spectrum identification** with reference library
- **Dark mode** support
- **PWA-ready** with manifest and icons

## License

MIT

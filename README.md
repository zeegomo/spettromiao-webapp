# KAT Spectrometer Webapp

Mobile webapp for the KAT DIY Raman spectrometer. This is the frontend that runs in your browser and communicates with the Raspberry Pi API server.

## Architecture

```
Phone Browser ─────> GitHub Pages (webapp)
      │
      │ (WiFi: KAT-Spectrometer)
      │
      └─────────────> Raspberry Pi (API server at 192.168.4.1:1312)
```

1. Phone loads webapp from GitHub Pages (or other hosting)
2. Phone connects to Pi's WiFi hotspot
3. Webapp calls Pi API for camera control and spectrum capture
4. Data stored locally in browser (IndexedDB)

## Deployment to GitHub Pages

### 1. Create GitHub Repository

```bash
cd kat-webapp
git init
git add .
git commit -m "Initial commit"
gh repo create kat-webapp --public --source=. --push
```

### 2. Enable GitHub Pages

1. Go to repository Settings > Pages
2. Source: Deploy from branch
3. Branch: `main` / `root`
4. Save

Your webapp will be available at: `https://yourusername.github.io/kat-webapp`

## Configuration

### Pi IP Address

If your Pi uses a different IP than `192.168.4.1`, edit `js/app.js`:

```javascript
// Line 14
const PI_API_URL = 'http://192.168.4.1:1312';
```

### PWA Icons

Add your icons to the `icons/` directory:
- `icon-192.png` (192x192)
- `icon-512.png` (512x512)
- `apple-touch-icon.png` (180x180)

## Mixed Content Warning

GitHub Pages serves over HTTPS, but the Pi API runs on HTTP. This may cause "mixed content" warnings in some browsers.

**Workarounds:**

- **iOS Safari**: Usually allows mixed content for local IPs
- **Android Chrome**: May need to enable "Insecure content" in site settings
- **Desktop browsers**: Click the shield/lock icon and allow insecure content

If mixed content is a persistent issue, consider hosting the webapp on your own HTTP server or serving it directly from the Pi.

## Updating the Webapp

1. Make changes to files
2. Bump version in `sw.js` (change `CACHE_NAME = 'kat-mobile-v2'`)
3. Commit and push

```bash
git add .
git commit -m "Update webapp"
git push
```

The service worker will detect the new version and update on next visit.

## File Structure

```
kat-webapp/
├── index.html          # Main page
├── manifest.json       # PWA manifest
├── sw.js              # Service worker
├── css/
│   └── style.css      # Styles
├── js/
│   ├── app.js         # Main app logic
│   ├── db.js          # IndexedDB storage
│   ├── identifier.js  # Spectrum identification
│   └── sync.js        # CouchDB sync
└── icons/             # PWA icons (add your own)
```

## Features

- Wizard-style interface for field testing
- Offline-capable (PWA)
- Local data storage (IndexedDB)
- Optional sync to CouchDB server
- Browser-based spectrum identification

## License

MIT

# Why Google Play Protect blocks MIMO's APK

Date: 2026-11-27. Evidence taken from the built APKs (`android/app/build/outputs/apk/`) with
`aapt2`, `apksigner` and the Gradle manifest-merge log — not from memory of what the code was meant
to do.

**Short answer:** the build you installed was a **debug** APK — `android:debuggable="true"`, signed
with the public AOSP debug certificate (`CN=Android Debug, O=Android`). Play Protect blocks those on
sight. On top of that, MIMO's honest capability set — read any screen, tap anywhere, capture the
display, use the microphone, talk to a server — is the same shape as a screen-reading trojan, and a
sideloaded app with that shape scores high regardless of intent. Both are addressed below; one is
fixed in the new build, the other cannot be removed without removing the product.

## 1. Package identity and build

| Item | Debug APK (blocked) | New release APK |
|---|---|---|
| Package | `com.mimo.companion` | same |
| versionCode / name | 2 / `1.1-debug` | **3 / 1.1.1** |
| minSdk / targetSdk / compileSdk | 26 / 37 / 37 | same |
| `android:debuggable` | **true** | false |
| Signing certificate | `CN=Android Debug, O=Android, C=US` (the well-known AOSP debug key) | `CN=MIMO Personal, O=MIMO, C=IN`, RSA-4096, SHA-256 `EF:E2:70:9E:34:89:CB:D1:7B:59:D4:29:1E:53:94:C8:90:74:9B:F0:7E:74:12:50:F6:F2:43:B3:C6:DE:E3:D9` |
| Signature scheme | v2 only | v2 |
| Size | 65,009,471 B | 45,854,123 B |

The debug key is not secret — it ships with the Android SDK, anybody can sign with it, and Google
treats every app signed with it as an untrusted test artifact. A debug build also allows `adb`
debugging and code injection. Play Protect's "App blocked to protect your device" is its standard
response to that combination, and it is a correct response.

## 2. Every permission the APK requests

From `aapt2 dump badging` on the built APK:

| Permission | Level | Why it is there | Could it go? |
|---|---|---|---|
| `INTERNET` | normal | Talks to your MIMO backend | No — the whole product |
| `POST_NOTIFICATIONS` | dangerous (runtime) | Task-finished and approval notifications | Only by removing notifications |
| `RECORD_AUDIO` | dangerous (runtime) | The push-to-talk microphone (Android speech recogniser) | Only by removing voice input |
| `FOREGROUND_SERVICE` | normal | The capture service must run in the foreground to be legal | No |
| `FOREGROUND_SERVICE_MEDIA_PROJECTION` | normal | Required by Android 14+ for screen capture | Required with capture |
| `com.mimo.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` | signature (own app) | Added by AndroidX Core for internal broadcasts; cannot leak outside the app | Added by the library |
| `ACCESS_NETWORK_STATE` | normal | **Not used by MIMO's code.** It is merged in by `com.google.android.datatransport:transport-backend-cct`, which arrives with ML Kit's text recogniser | Not safely — see §4 |

Not requested, deliberately: `SYSTEM_ALERT_WINDOW` (no overlay), `READ_SMS`, `CALL_LOG`,
`READ_CONTACTS`, `MANAGE_EXTERNAL_STORAGE`, `REQUEST_INSTALL_PACKAGES`, `BIND_DEVICE_ADMIN`,
`QUERY_ALL_PACKAGES`, camera, location, and no `READ_LOGS`. MIMO cannot install anything, cannot read
messages, cannot see other apps' data through the storage API, and cannot become a device
administrator.

## 3. The accessibility service

Shipped configuration (`res/xml/accessibility_service_config.xml`, verbatim):

```
accessibilityEventTypes = typeWindowStateChanged | typeWindowContentChanged
accessibilityFeedbackType = feedbackGeneric
accessibilityFlags = flagReportViewIds | flagRetrieveInteractiveWindows | flagIncludeNotImportantViews
canPerformGestures = true
canRetrieveWindowContent = true
isAccessibilityTool = false
notificationTimeout = 200
```

What that means in practice:

- **It can read the active window's view tree**: the text of what is on screen, view ids,
  accessibility labels, and which elements are tappable or editable.
- **It can perform gestures** — tap a point, swipe — as a fallback when a node refuses a click, and
  it **can type** into a field via `ACTION_SET_TEXT`.
- **It is not an assistive tool** (`isAccessibilityTool=false`): MIMO is automation, not an aid for
  disabled users. Declaring `true` would be a false declaration and a Play policy breach. The cost is
  Android's "Restricted setting" flag on a sideloaded app.
- **It does not receive every event**: only window changes, and since V1.0 it no longer walks the view
  tree on events at all — a read happens only when you press a button on the Operator screen. There
  is no background loop, no overlay, and no timer.

The service is bound with `BIND_ACCESSIBILITY_SERVICE`, so only Android's own settings can enable it,
and only you can enable it. It stops when you turn it off. This is the single most powerful thing in
the app, and it is the reason a security scanner scores MIMO highly.

## 4. Unnecessary or library-supplied permissions

`ACCESS_NETWORK_STATE` was declared by the app and used nowhere (no `ConnectivityManager` call in the
source). It has been removed from `AndroidManifest.xml`; the merged manifest still contains it because
ML Kit's dependency chain (`com.google.android.datatransport:transport-backend-cct`) adds it back.
Removing it with `tools:node="remove"` would strip a normal-level permission from a library that may
check connectivity before delivering telemetry — untested on a device, so it is not in this build.
It is normal-level (no prompt, no user-visible access) and grants only "can you see whether the
network is up".

**Data collection, stated plainly:** ML Kit's on-device recogniser is bundled (no model download, no
network call to recognise text), but its dependency chain carries Google's Data Transport library,
which is the mechanism Firebase/ML Kit uses to batch usage metrics. Nothing in MIMO's code configures
it, and no analytics SDK is present (no `firebase-analytics`, `crashlytics`, `installations`), but the
machinery is there and I will not claim otherwise. If you want an app that contains **zero** Google
telemetry, the option is to drop ML Kit OCR (the APK also shrinks by ~40 MB) and keep
accessibility-tree text only — say the word and I will build that variant.

## 5. Certificate and signing

- Blocked build: debug key, `5 v2`, debuggable — as above.
- New build: a **private release key generated on this machine** at `~/.mimo/keys/mimo-release.jks`
  (4096-bit RSA, 10,000 days). It is **not** in the repository, not in the source ZIP, and not
  attached anywhere. Back it up: if it is lost, future versions cannot install over this one.
- Reproducible: `MIMO_KEYSTORE`, `MIMO_KEYSTORE_PASSWORD`, `MIMO_KEY_ALIAS`, `MIMO_KEY_PASSWORD`,
  then `./gradlew :app:assembleRelease`.

Signing does not make the capabilities smaller. It removes the "untrusted debug artifact" signal,
which is the one Play Protect applies mechanically to every debug build.

## 6. What could make Play Protect flag accessibility/screen reading

These are the properties of MIMO that a classifier reacts to, each verified in the code:

1. **Accessibility + capture + microphone + internet in one app.** The signature of a remote-access
   trojan: read the screen, act on it, listen, and exfiltrate. MIMO does the first three only when
   you press a button, and sends nothing but chat text to the address you configure.
2. **Sideloaded, self-signed, no Play distribution.** There is no developer verification and no Play
   review behind it.
3. **Debug build.** Fixed.
4. **Cleartext HTTP allowed** (`usesCleartextTraffic="true"` plus a permissive network security
   config) because the backend runs on your LAN over plain HTTP. The app refuses a plain-HTTP address
   whose host is not loopback or RFC1918, so a token cannot cross the internet in the clear — but the
   flag itself is a red mark on a scanner's list.
5. **`allowBackup="true"`** — normal for a personal app, but it means the system may include app data
   in a device backup.

## 7. Code audit — nothing suspicious

Grep of the whole app source (`android/app/src/main/java`), results:

| Check | Result |
|---|---|
| `Runtime.getRuntime`, `ProcessBuilder`, `exec` | none |
| Reflection / `DexClassLoader` / dynamic code loading | none |
| `WebView` / `setJavaScriptEnabled` | none (no WebView at all) |
| Hard-coded network endpoints | none — the only URL is the `http://192.168.0.151:8000` **placeholder** in the settings field and the private-host validation |
| Analytics / tracking SDKs | none (`firebase-analytics`, `crashlytics`, `installations`, Facebook, Amplitude, Mixpanel, Sentry, Adjust, AppsFlyer — absent) |
| Dependencies | AndroidX (Compose, Room, DataStore, Navigation, Lifecycle), OkHttp, kotlinx-serialization, ML Kit text-recognition. That is the complete list. |
| Where data goes | only to the backend URL you type; OCR runs on the device with the bundled model; no upload of screenshots or screen text anywhere |
| Broadcast receivers | one, `exported=false`, added by AndroidX |

## 8. Against Google Play policy

If MIMO were published on Play (it is not), these would decide whether it is accepted:

- **Accessibility API policy:** permitted only for apps whose *core* function needs it, with
  disclosure and an accessibility declaration. MIMO's operator is a core function, but Google's bar
  for automation apps is high and often rejected. This is a distribution question, not a malware one.
- **`MediaProjection` policy:** allowed with a clear in-app disclosure and permanent notification —
  which MIMO has.
- **Sideloading** is not a Play policy matter; Play Protect simply scans anything installed outside
  Play. An app with this capability profile will keep drawing scrutiny however it is signed.

## 9. What to do about the block

In order of preference, and none of them hides anything:

1. **Install the signed release build** (attached). It is not debuggable, it is signed with its own
   key, and it has one permission fewer. If Play Protect still warns, that is the capability profile,
   not the certificate.
2. **Install over `adb`** — `adb install -r app-release.apk`. Play Protect's on-install check applies
   to packages delivered by other apps; an `adb` install from your own PC is the standard path for a
   personal build and does not disable anything.
3. **Samsung's Auto Blocker** (One UI 6.1+) blocks sideloading by default and shows its own message
   ("Auto Blocker prevented installation"). It is separate from Play Protect. Changing it is your
   decision, not something I will talk you into; the settings path is *Settings → Security and
   privacy → Auto Blocker*.
4. **Report it as a false positive.** Google's channel for a blocked sideloaded app is the Play
   Protect "Report a problem" flow in the Play Store app (menu → Help & feedback → Send feedback),
   and for app developers the Play Console support form "Report a Play Protect issue". Include the
   package name, the certificate fingerprint above, and a one-line description: *personal automation
   client for a self-hosted assistant; accessibility and screen capture are user-initiated only; no
   data leaves the device except to the user's own server.* Expect a human review to take days and
   not to be guaranteed — Google does not owe a self-signed automation app a waiver.
5. **Play internal testing** (the only durable fix if you want it to install cleanly on phones):
   a Play Console account, an `.aab`, the accessibility declaration, and internal-track distribution.
   That path is a publishing decision, not a code fix.

What I have not done and will not do: disable Play Protect, hide permissions, split the operator into
an obfuscated plugin, use a repackaged certificate, or strip the disclosure strings.

## The build being delivered

`MIMO-companion-1.1.1-release.apk` — versionCode 3, versionName 1.1.1, signed with the MIMO Personal
key, not debuggable, one permission fewer than the debug build, and identical functionality. Install
it with `adb install -r` if the phone's installer still complains.

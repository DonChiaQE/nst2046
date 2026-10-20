# macOS HIG brief for the ATC demo app

Date: 2026-10-20. Source: Apple Human Interface Guidelines (HIG), read through the JSON behind each page. Each point cites its page. "(our inference)" and "(not in HIG)" mark our own reading.

## 1. Window and layout

- Use the large display to show more with fewer nested levels and less modality: transcript, instructions and conflicts side by side in one window, not in sheets. (https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)
- Use a split view: live transcript in the main pane, instructions and conflicts in an adjacent pane. A split view can hold supplementary panes, like the Keynote inspector. (https://developer.apple.com/design/human-interface-guidelines/split-views)
- Make the side panel an inspector, not a sidebar. A sidebar sits on the leading side for navigation. An inspector "typically presents information on the trailing side of a split view" and updates with the selection. (https://developer.apple.com/design/human-interface-guidelines/sidebars, https://developer.apple.com/design/human-interface-guidelines/windows, https://developer.apple.com/design/human-interface-guidelines/panels)
- Add a leading sidebar only for real navigation (for example, saved sessions), and do not hide it by default. (https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Let people hide the inspector, with several ways back: a trailing toolbar button and a View menu command. Option-Command-I is the standard inspector shortcut. Menu titles follow state ("Show Inspector", "Hide Inspector"). (https://developer.apple.com/design/human-interface-guidelines/split-views, https://developer.apple.com/design/human-interface-guidelines/keyboards, https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- Set minimum and maximum pane sizes so the divider stays visible; use the thin 1 pt divider. The HIG gives no numeric macOS window minimum; windows must adapt fluidly to size. (https://developer.apple.com/design/human-interface-guidelines/split-views, https://developer.apple.com/design/human-interface-guidelines/windows)
- Keep Talk and conflict status off the bottom of the window; people often move windows so the bottom edge is off screen. (https://developer.apple.com/design/human-interface-guidelines/layout)
- Put the most important items near the top and leading side; newest or most severe conflict first. (https://developer.apple.com/design/human-interface-guidelines/layout)
- Toolbar: at most three groups. Leading: title. Center: role picker. Trailing: inspector button and the one primary action. Mirror every toolbar item in the menu bar. (https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Window title under 15 characters, about the content, not the app name ("Live Session"). (https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Support system full screen (Control-Command-F). Keep Talk and the inspector reachable there, since the menu bar hides. (https://developer.apple.com/design/human-interface-guidelines/going-full-screen, https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- Use the system window frame, no custom chrome. (https://developer.apple.com/design/human-interface-guidelines/windows)
- Persistently highlight the selection in each pane; selecting a conflict could highlight its transcript lines (our inference). (https://developer.apple.com/design/human-interface-guidelines/split-views)
- Show extracted instructions as a table with noun column headings; macOS tables let people sort and resize columns. (https://developer.apple.com/design/human-interface-guidelines/lists-and-tables)
- Restore window size, inspector state and role on relaunch. (https://developer.apple.com/design/human-interface-guidelines/launching)

## 2. Controls for talking

- Make Talk the one prominent button (one or two per view at most); in a toolbar, `.prominent` goes on one primary action at the trailing side. (https://developer.apple.com/design/human-interface-guidelines/buttons, https://developer.apple.com/design/human-interface-guidelines/toolbars)
- A toggle-like button (start, then stop) changes its appearance with state, for example its background, never by color alone. (https://developer.apple.com/design/human-interface-guidelines/toggles)
- Give custom buttons a press state. macOS default control size is 28x28 pt, minimum 20x20 pt. (https://developer.apple.com/design/human-interface-guidelines/buttons, https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Pilot vs Controller: a two-segment segmented control in the toolbar, noun labels in title case, text only, a tooltip per segment. Switches, checkboxes and radio buttons do not belong in a toolbar. (https://developer.apple.com/design/human-interface-guidelines/segmented-controls, https://developer.apple.com/design/human-interface-guidelines/toggles)
- Custom shortcuts only for the most frequent commands (Talk, switch role). Command is the main modifier, Shift secondary, Option sparingly, never Control. Do not reuse standard shortcuts (Command-Space is Spotlight). (https://developer.apple.com/design/human-interface-guidelines/keyboards)
- Esc means "cancel the current action or process", so it fits stopping a recording (our inference). (https://developer.apple.com/design/human-interface-guidelines/keyboards)
- Hold-to-talk is not covered (not in HIG). Also offer click to start and stop, so the core action works through more than one interaction. (https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Support Full Keyboard Access. (https://developer.apple.com/design/human-interface-guidelines/keyboards)
- Tooltips start with a verb, use sentence case, stay under 60 to 75 characters. (https://developer.apple.com/design/human-interface-guidelines/offering-help)

## 3. Showing live state and urgency

- Match delivery to significance: passive status for status, interruption only when people must act. Put status beside what it describes. (https://developer.apple.com/design/human-interface-guidelines/feedback)
- Recording: the Breathe symbol animation suits "an ongoing recording session"; Variable Color can show level. Add a "Recording" label. (https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Show partial transcript text at once, never an empty wait. (https://developer.apple.com/design/human-interface-guidelines/loading)
- For background work (the Claude extraction call), a small unlabeled spinner in a consistent spot. If it stalls, say why. (https://developer.apple.com/design/human-interface-guidelines/progress-indicators)
- Show conflicts inline, not as alerts. Alerts interrupt; use them sparingly, never merely to inform or at launch. A demo conflict is something to watch, not a decision (our inference). (https://developer.apple.com/design/human-interface-guidelines/alerts)
- Never more than one alert at a time. (https://developer.apple.com/design/human-interface-guidelines/modality)
- Make the levels differ in shape, text and color: READBACK as `exclamationmark.triangle`, orange, "Readback"; RUNWAY as `exclamationmark.octagon.fill`, red, "Runway conflict" (our mapping). Never color alone, never one color for two meanings. (https://developer.apple.com/design/human-interface-guidelines/color, https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Sound is optional and never the only cue; pair it with a visual cue. A sound played while recording may reach the microphone (our inference). (https://developer.apple.com/design/human-interface-guidelines/notifications, https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Skip notifications: a frontmost app's notifications do not appear, so add data to the current view. Critical notifications are for health and safety and need an entitlement. (https://developer.apple.com/design/human-interface-guidelines/notifications, https://developer.apple.com/design/human-interface-guidelines/managing-notifications)
- Do not auto-dismiss conflict cards on a timer. (https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Keep motion on frequent updates (new rows) brief or absent. (https://developer.apple.com/design/human-interface-guidelines/motion)

## 4. Visual style

- Use semantic system colors (label, secondary label, separator, window background, accent) through APIs; never hard-code values or repurpose them. Custom colors need light, dark and increased contrast variants. (https://developer.apple.com/design/human-interface-guidelines/color)
- Follow the system appearance; no in-app light or dark setting. Test with Increase Contrast and Reduce Transparency. (https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- Contrast at least 4.5:1 for text up to 17 pt, 3:1 for 18 pt or bold; aim for 7:1 for small custom-colored text. (https://developer.apple.com/design/human-interface-guidelines/accessibility, https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- Liquid Glass: standard bars get it automatically. Keep it out of the content layer (transcript rows, conflict cards), which uses standard materials. Use it sparingly on custom controls. (https://developer.apple.com/design/human-interface-guidelines/materials)
- Color on glass only for status indicators or primary actions, applied to the button background. Keep the toolbar monochrome. (https://developer.apple.com/design/human-interface-guidelines/color, https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Type: SF Pro, default 13 pt, minimum 10 pt; built-in text styles (Body 13, Headline 13 bold, Title 3 15, Caption 10); no Ultralight, Thin or Light. (https://developer.apple.com/design/human-interface-guidelines/typography)
- SF Mono is in the system family. Monospaced digits for times, runways and callsigns is our choice (not in HIG). (https://developer.apple.com/design/human-interface-guidelines/typography)
- Make transcript text selectable. (https://developer.apple.com/design/human-interface-guidelines/labels)
- Symbols: borderless in the toolbar, outline in toolbars and lists, slash variant for unavailable (`mic.slash` when access is denied). (https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Candidates checked in this Mac's symbol catalog (not in HIG): `mic`, `mic.fill`, `waveform`, `airplane`, `airplane.departure`, `airplane.arrival`, `road.lanes` (no runway symbol exists), `exclamationmark.octagon`, `headset`, `hand.raised`, `antenna.radiowaves.left.and.right`. Confirm in the SF Symbols app. (https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- App icon: layered, built in Icon Composer from square unmasked layers; simple shapes; no text, photos or Apple hardware; no added shadows; default, dark, clear and tinted variants. SF Symbols are prohibited in app icons, so draw the airplane yourself. (https://developer.apple.com/design/human-interface-guidelines/app-icons, https://developer.apple.com/design/human-interface-guidelines/sf-symbols)

## 5. Privacy and permissions

- The microphone needs permission; the system alert shows your purpose string. Ask when the person first presses Talk, not at launch. (https://developer.apple.com/design/human-interface-guidelines/privacy)
- Purpose string: one brief, complete, active sentence in sentence case, ending with a period, saying how and why. Apple's example: "The app records during the night to detect snoring sounds." Ours: "This app uses the microphone to transcribe the radio calls you speak." (https://developer.apple.com/design/human-interface-guidelines/privacy)
- The HIG does not name speech recognition; if the speech API asks separately, write that string the same way (not in HIG). (https://developer.apple.com/design/human-interface-guidelines/privacy)
- Process on device where possible, and be transparent: if the Claude extractor sends transcript text off the Mac, say so where people pick it. (https://developer.apple.com/design/human-interface-guidelines/privacy)
- Optional pre-prompt view: one button, "Continue" (never "Allow"), and no close or cancel. (https://developer.apple.com/design/human-interface-guidelines/privacy)
- After denial: no alert. An inline message with `mic.slash` saying why Talk cannot work, plus a button that opens System Settings, where people change the choice. (https://developer.apple.com/design/human-interface-guidelines/privacy, https://developer.apple.com/design/human-interface-guidelines/alerts, https://developer.apple.com/design/human-interface-guidelines/feedback, https://developer.apple.com/design/human-interface-guidelines/writing)
- After granting: start recording, no success message; people mainly need to hear about failure. (https://developer.apple.com/design/human-interface-guidelines/feedback)

## 6. Accessibility

- Give every control a descriptive VoiceOver label ("Start talking as Controller") and update it with state. (https://developer.apple.com/design/human-interface-guidelines/voiceover)
- Inform VoiceOver of visible changes, such as a new conflict. Announcing each partial word would be noise (our inference). (https://developer.apple.com/design/human-interface-guidelines/voiceover)
- Group each instruction row into one element; use headings ("Transcript", "Instructions", "Conflicts"); hide decorative images. (https://developer.apple.com/design/human-interface-guidelines/voiceover)
- Under Reduce Motion, cut repeating animation (breathing mic, sliding rows) and prefer fades. Motion is never the only signal. (https://developer.apple.com/design/human-interface-guidelines/accessibility, https://developer.apple.com/design/human-interface-guidelines/motion)
- macOS has no Dynamic Type. Let people enlarge text, ideally to 200 percent, through custom UI (View menu text size); let rows grow, do not truncate. (https://developer.apple.com/design/human-interface-guidelines/typography, https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Offer typed input for people who prefer text to speech. (https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Pad about 12 pt around bezeled controls, 24 pt around borderless ones. Audit with Accessibility Inspector. (https://developer.apple.com/design/human-interface-guidelines/accessibility)

## 7. Writing

- Keep one voice and a term list ("Controller", "Runway conflict", always the same words). (https://developer.apple.com/design/human-interface-guidelines/writing)
- Plain, direct tone; no "oops", no "we"; errors near the problem, saying how to fix it. (https://developer.apple.com/design/human-interface-guidelines/writing)
- Buttons start with a verb in title case ("Start Talking"); add an ellipsis if a button opens another window. (https://developer.apple.com/design/human-interface-guidelines/buttons)
- Column labels are nouns in title case, no ending punctuation. (https://developer.apple.com/design/human-interface-guidelines/lists-and-tables)
- Any alert: specific title (not "Error"), buttons naming the result, "Cancel" to cancel, "OK" only for pure information. (https://developer.apple.com/design/human-interface-guidelines/alerts)
- Empty states give a next step: "No instructions yet. Press Talk and read a clearance." (https://developer.apple.com/design/human-interface-guidelines/writing)

## 8. Ten rules

Each rule restates points above; the slug in brackets is the page at https://developer.apple.com/design/human-interface-guidelines/ plus that slug.

1. Do put instructions and conflicts in a trailing inspector pane; don't use a leading sidebar. [windows]
2. Do make Talk the one prominent toolbar action, with a menu command and shortcut; don't put it at the window bottom. [toolbars, layout]
3. Do show conflicts with symbol, text and color; never color alone. [accessibility]
4. Don't raise an alert or notification per conflict; keep alerts for critical, actionable problems. [alerts]
5. Do use semantic colors, text styles and standard controls; don't put Liquid Glass on content. [materials]
6. Do request the microphone on first Talk with a specific purpose string; never label a pre-prompt "Allow". [privacy]
7. Do handle denial inline with a System Settings button; don't block with an alert. [feedback]
8. Do label every control and announce new conflicts; stop repeating animation under Reduce Motion. [voiceover]
9. Do support Full Keyboard Access and full screen; don't repurpose standard shortcuts. [keyboards]
10. Do restore window state on relaunch; don't add an in-app appearance setting. [launching, dark-mode]

Pages not read: inspectors and liquid-glass (both 404; no such pages). Inspector guidance comes from windows, panels and toolbars; Liquid Glass guidance from materials, color and toolbars.

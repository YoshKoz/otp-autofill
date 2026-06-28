// Background broker: content scripts can't use nativeMessaging directly, so
// they ask the background page, which queries the native host on demand.
// The native host process is spawned per-query and exits immediately after.

const HOST = "otp_autofill";

browser.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== "queryCode") return;
  // Trust the SENDER's URL for the hostname, never a value from the page DOM.
  let hostname = "";
  try {
    hostname = new URL(sender.url || (sender.tab && sender.tab.url) || "").hostname;
  } catch (e) {
    hostname = "";
  }
  if (!hostname) return Promise.resolve({});

  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; try { port.disconnect(); } catch (e) {} resolve(v); } };

    let port;
    try {
      port = browser.runtime.connectNative(HOST);
    } catch (e) {
      return resolve({ error: "connectNative failed: " + e });
    }
    port.onMessage.addListener((resp) => done(resp || {}));
    port.onDisconnect.addListener(() => done({ error: "host disconnected" }));
    // armTs is supplied by the content script (when it first saw the OTP field).
    port.postMessage({ hostname, armTs: msg.armTs });
    setTimeout(() => done({}), 4000); // hard timeout per query
  });
});

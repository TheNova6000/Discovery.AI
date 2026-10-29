/*
 * One runtime config for every page: decides OFFLINE vs ONLINE from where the
 * page is served, so the same files work in both places with no edits.
 *
 *   OFFLINE  (http://localhost:8000, 127.0.0.1, a LAN/VM IP, file://)
 *            frontend and backend on the same origin, no login.
 *   ONLINE   (https://discovery-ai.vercel.app or any host listed below)
 *            backend on Render, Google login through Supabase.
 *
 * To point the online site at a different backend or auth project, edit
 * ONLINE only. To force a mode while testing, add ?mode=offline or
 * ?mode=online to the page URL. See docs/Deployment.md.
 */
(function () {
  var ONLINE = {
    MODE: "online",
    BACKEND_URL: "https://discovery-ai-bosm.onrender.com",
    SUPABASE_URL: "https://etamqvymleodnacznmnj.supabase.co",
    // Supabase "anon" key: public by design (it is shipped to every browser);
    // access is enforced by the backend verifying the user's JWT.
    SUPABASE_ANON_KEY:
      "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV0YW1xdnltbGVvZG5hY3pubW5qIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc4OTQyMzQsImV4cCI6MjEwMzQ3MDIzNH0.WA0IH9Ug5QP4ZzrJ0-Xe5jvqRS2bp16cTmrNvRrTG3M",
  };
  var OFFLINE = { MODE: "offline", BACKEND_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" };
  var ONLINE_HOST_SUFFIXES = [".vercel.app"];

  var forced = new URLSearchParams(window.location.search).get("mode");
  var host = window.location.hostname || "";
  var online = ONLINE_HOST_SUFFIXES.some(function (suffix) {
    return host === suffix.slice(1) || host.endsWith(suffix);
  });
  if (forced === "online") online = true;
  if (forced === "offline") online = false;

  window.DISCOVERY_RUNTIME = Object.freeze(online ? ONLINE : OFFLINE);
})();

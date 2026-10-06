// A plain script that runs before the window's modules: if one of the window's files did not
// arrive (a connection dropped while they loaded), the page loads again once, with the same
// address and its key; if that fails too, it says what to do instead of staying empty.

(function () {
  "use strict";
  var KEY = "cw-control-reloaded";
  var done = false;

  function failed() {
    if (done) return;
    done = true;
    var again = true;
    try {
      again = window.sessionStorage.getItem(KEY) === "1";
      window.sessionStorage.setItem(KEY, "1");
    } catch (error) {
      again = true;
    }
    if (!again) {
      window.location.reload();
      return;
    }
    var main = document.getElementById("main");
    if (!main) return;
    var box = document.createElement("div");
    box.className = "boot-failed";
    box.setAttribute("role", "alert");
    var title = document.createElement("h1");
    title.textContent = "This window could not load";
    var text = document.createElement("p");
    text.textContent =
      "Part of it did not arrive. Press ⌘R to load it again; if it stays empty, quit ComplianceWatch Control and open it again.";
    box.append(title, text);
    main.replaceChildren(box);
  }

  var app = document.querySelector('script[type="module"]');
  if (app) app.addEventListener("error", failed);
  window.addEventListener("load", function () {
    if (!document.styleSheets.length) failed();
  });
})();

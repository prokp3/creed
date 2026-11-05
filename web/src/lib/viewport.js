// On iPhone, a home-screen app can be told the page is shorter than the screen, which leaves a gap under the tab
// bar. The app really does fill the whole screen there, so its height comes from the screen itself.
export function fillTheScreen(win = window) {
  const { navigator: nav, screen, document: doc } = win;
  const standalone = nav.standalone === true || win.matchMedia('(display-mode: standalone)').matches;
  if (!standalone || !/iPhone/.test(nav.userAgent)) return false;

  const apply = () => {
    const portrait = win.matchMedia('(orientation: portrait)').matches;
    const long = Math.max(screen.width, screen.height);
    const short = Math.min(screen.width, screen.height);
    doc.documentElement.style.setProperty('--app-height', `${portrait ? long : short}px`);
  };
  apply();
  win.addEventListener('resize', apply);
  return true;
}

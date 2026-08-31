import { Link, NavLink, Outlet } from 'react-router-dom';

/**
 * The shell every page renders inside: header, navigation, footer.
 *
 * The Figma top bar - brand mark on the left, navigation to the right. `NavLink`
 * rather than `Link` for the navigation so the active item is marked with
 * `aria-current`, which is both what the design's underline hangs off and what
 * a screen reader announces.
 *
 * "Inspections" is the stored history and "New scan" is the workspace that
 * adds to it - the two are separate items because they are separate screens,
 * and collapsing them would leave one of the app's two working screens with no
 * route in the navigation at all.
 *
 * Pages render into `<Outlet />` and should not repeat chrome. The disclaimer
 * in the footer is deliberate and belongs on every page - see the note there.
 */
export function AppLayout() {
  return (
    <div className="app-layout">
      <header className="app-header">
        <Link to="/" className="app-header__title">
          <span className="app-header__mark" aria-hidden="true">
            LM
          </span>
          Metrology Compliance
        </Link>
        <nav className="app-nav" aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/inspections">Inspections</NavLink>
          <NavLink to="/scan">New scan</NavLink>
        </nav>
      </header>

      <main className="app-main">
        <Outlet />
      </main>

      <footer className="app-footer">
        {/*
          Shown on every page, not just the results screen. This tool assists a
          human reviewer; it does not certify legal compliance, and a user must
          never be able to reach a verdict without seeing that stated.
        */}
        <p className="app-footer__disclaimer">
          This tool provides automated assistance for reviewing packaged
          commodity labels. It is not a legal determination and does not
          certify compliance with the Legal Metrology (Packaged Commodities)
          Rules, 2011. Always confirm findings against the authoritative rules.
        </p>
      </footer>
    </div>
  );
}

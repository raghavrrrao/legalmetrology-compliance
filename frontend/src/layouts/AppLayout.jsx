import { Link, NavLink, Outlet } from 'react-router-dom';

/**
 * The shell every page renders inside: header, navigation, footer.
 *
 * `NavLink` rather than `Link` for the navigation so the active item is marked
 * with `aria-current`, which is both what the active treatment hangs off and
 * what a screen reader announces.
 *
 * "Inspections" is the stored history and "New scan" is the workspace that
 * adds to it - the two are separate items because they are separate screens,
 * and collapsing them would leave one of the app's two working screens with no
 * route in the navigation at all. "New scan" is drawn as the primary action
 * rather than a third link: it is what a visitor came to do.
 *
 * Pages render into `<Outlet />` and should not repeat chrome. The disclaimer
 * in the footer is deliberate and belongs on every page - see the note there.
 */
export function AppLayout() {
  return (
    <div className="app-layout">
      {/*
        First in the tab order, hidden until focused. The header carries a
        brand link and three navigation items; without this a keyboard user
        tabs through all four on every page before reaching the content they
        came for. `#main` is the `<main>` below, which takes focus because it
        is given `tabIndex={-1}` - a bare anchor jump moves the viewport but
        not the focus ring in several browsers, and the next Tab would then
        continue from the header.
      */}
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="app-header">
        <Link to="/" className="app-header__title">
          <BrandMark />
          <span className="app-header__words">
            <span className="app-header__name">LM Metrology</span>
            <span className="app-header__tagline">Compliance Assistant</span>
          </span>
        </Link>

        <nav className="app-nav" aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/inspections">Inspections</NavLink>
          <NavLink to="/scan" className="app-nav__cta">
            New scan
          </NavLink>
        </nav>
      </header>

      <main className="app-main" id="main" tabIndex={-1}>
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

/**
 * The brand mark: a package with a scan line across it.
 *
 * Drawn rather than lettered so the identity survives at 24px in a browser tab
 * strip and on a phone header, where two initials in a box read as noise. It is
 * deliberately generic geometry — a carton and a beam. **It is not an emblem
 * and must never become one:** this is an independent tool, and a mark that
 * borrowed the visual language of a government seal would imply an
 * authorisation nobody has given it.
 */
function BrandMark() {
  return (
    <span className="app-header__mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
        <path
          d="M12 3 4 6.6v7.9c0 .5.3 1 .7 1.2L12 21l7.3-5.3c.4-.2.7-.7.7-1.2V6.6L12 3Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path
          d="M4 6.6 12 10l8-3.4M12 10v11"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
          opacity="0.45"
        />
        <path
          d="M6.5 12.4h11"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

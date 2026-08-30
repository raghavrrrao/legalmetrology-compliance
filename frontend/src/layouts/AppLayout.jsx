import { Link, Outlet } from 'react-router-dom';

/**
 * The shell every page renders inside: header, navigation, footer.
 *
 * Pages render into `<Outlet />` and should not repeat chrome. The disclaimer
 * in the footer is deliberate and belongs on every page - see the note there.
 */
export function AppLayout() {
  return (
    <div className="app-layout">
      <header className="app-header">
        <Link to="/" className="app-header__title">
          Legal Metrology Compliance Checker
        </Link>
        <nav className="app-nav">
          <Link to="/">Home</Link>
          <Link to="/scan">Scan a label</Link>
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

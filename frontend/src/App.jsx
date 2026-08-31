import { Route, Routes } from 'react-router-dom';

import { AppLayout } from './layouts/AppLayout.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { InspectionsPage } from './pages/InspectionsPage.jsx';
import { NotFoundPage } from './pages/NotFoundPage.jsx';
import { ResultPage } from './pages/ResultPage.jsx';
import { ScanPage } from './pages/ScanPage.jsx';

/**
 * Application routes.
 *
 * Feature branches add their routes here as children of AppLayout, so every
 * page inherits the shared chrome and the compliance disclaimer.
 *
 * `result/:checkId` is a deep link to a stored `ComplianceCheck`. It exists
 * because `GET /api/v1/compliance/<uuid>/` does: a result is meant to survive a
 * reload and be sendable to a reviewer, and without a route there was no way
 * for anyone to open one.
 *
 * `inspections` and `scan` are two screens, not one, because they answer two
 * questions: what has been assessed already, and assess this label now. The
 * breadcrumbs on the scan and result screens named an "Inspections" parent from
 * the start; this is the route that makes that name lead somewhere.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="inspections" element={<InspectionsPage />} />
        <Route path="scan" element={<ScanPage />} />
        <Route path="result/:checkId" element={<ResultPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

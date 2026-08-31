import { Route, Routes } from 'react-router-dom';

import { AppLayout } from './layouts/AppLayout.jsx';
import { HomePage } from './pages/HomePage.jsx';
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
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="scan" element={<ScanPage />} />
        <Route path="result/:checkId" element={<ResultPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

import { Route, Routes } from 'react-router-dom';

import { AppLayout } from './layouts/AppLayout.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { NotFoundPage } from './pages/NotFoundPage.jsx';

/**
 * Application routes.
 *
 * Feature branches add their routes here as children of AppLayout, so every
 * page inherits the shared chrome and the compliance disclaimer.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

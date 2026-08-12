import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { OverviewPage } from './pages/OverviewPage'
import { EntitiesPage } from './pages/EntitiesPage'
import { GraphPage } from './pages/GraphPage'
import { ScenariosPage } from './pages/ScenariosPage'
import { QueryPage } from './pages/QueryPage'
import { SupplyChainMapPage } from './pages/SupplyChainMapPage'
import { ImportPage } from './pages/ImportPage'
import { DependenciesPage } from './pages/DependenciesPage'
import { IngestionPage } from './pages/IngestionPage'
import { PlatformPage } from './pages/PlatformPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="data/import" element={<ImportPage />} />
          <Route path="data/entities" element={<EntitiesPage />} />
          <Route path="data/dependencies" element={<DependenciesPage />} />
          <Route path="data/ingestion" element={<IngestionPage />} />
          <Route path="simulation/scenarios" element={<ScenariosPage />} />
          <Route path="simulation/map" element={<SupplyChainMapPage />} />
          <Route path="simulation/graph" element={<GraphPage />} />
          <Route path="reasoning/query" element={<QueryPage />} />
          <Route path="platform" element={<PlatformPage />} />
          {/* Legacy paths */}
          <Route path="import" element={<Navigate to="/data/import" replace />} />
          <Route path="entities" element={<Navigate to="/data/entities" replace />} />
          <Route path="map" element={<Navigate to="/simulation/map" replace />} />
          <Route path="graph" element={<Navigate to="/simulation/graph" replace />} />
          <Route path="scenarios" element={<Navigate to="/simulation/scenarios" replace />} />
          <Route path="query" element={<Navigate to="/reasoning/query" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

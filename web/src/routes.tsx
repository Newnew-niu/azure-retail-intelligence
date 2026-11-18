import type { RouteObject } from 'react-router'

import { Layout } from './components/Layout'
import { AboutPage } from './pages/AboutPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { SellerListPage } from './pages/SellerListPage'

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <SellerListPage /> },
      {
        path: 'sellers/:sellerId',
        // Loaded on first visit: the chart library is most of the bundle and the list does not need it.
        lazy: async () => ({ Component: (await import('./pages/SellerDetailPage')).SellerDetailPage }),
      },
      { path: 'about', element: <AboutPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

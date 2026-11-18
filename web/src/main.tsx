import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider } from 'react-router'

import { createQueryClient } from './queryClient'
import { routes } from './routes'
import './styles.css'

// Hash URLs (#/sellers/...) work on any static host, including a GitHub Pages sub-path,
// without server rewrites. See docs/seller_health_decisions.md.
const router = createHashRouter(routes)
const queryClient = createQueryClient()

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root element')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)

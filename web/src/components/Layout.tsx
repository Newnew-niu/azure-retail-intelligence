import { Link, Outlet } from 'react-router'

export function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="container header-inner">
          <Link to="/" className="brand">
            Seller Health
          </Link>
          <p className="tagline">Marketplace seller performance, Olist data, Jan 2017 to Aug 2018</p>
        </div>
      </header>
      <main id="main" className="container" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container">
          <p>
            Health signals are illustrative rules for exploring seller performance. They are not a credit
            score and must not be used to make lending decisions.
          </p>
          <p>
            Data: Brazilian E-Commerce Public Dataset by Olist (CC BY-NC-SA 4.0), sales orders purchased
            from 2017-01-01 to 2018-08-31.
          </p>
        </div>
      </footer>
    </>
  )
}

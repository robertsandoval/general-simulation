import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Label,
  Masthead,
  MastheadBrand,
  MastheadContent,
  MastheadLogo,
  MastheadMain,
  MastheadToggle,
  Nav,
  NavGroup,
  NavItem,
  NavList,
  Page,
  PageSidebar,
  PageSidebarBody,
  PageToggleButton,
  SkipToContent,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core'
import BarsIcon from '@patternfly/react-icons/dist/esm/icons/bars-icon'
import { useHealthPoll } from '../hooks/useHealthPoll'

type NavLeaf = { to: string; label: string; end?: boolean }

type NavSection = {
  title: string
  items: NavLeaf[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Data',
    items: [
      { to: '/data/import', label: 'Import graph' },
      { to: '/data/entities', label: 'Entities' },
      { to: '/data/dependencies', label: 'Dependencies' },
      { to: '/data/ingestion', label: 'Ingestion' },
    ],
  },
  {
    title: 'Simulation',
    items: [
      { to: '/simulation/scenarios', label: 'Scenarios' },
      { to: '/simulation/map', label: 'Supply chain map' },
      { to: '/simulation/graph', label: 'Graph' },
    ],
  },
  {
    title: 'Reasoning',
    items: [{ to: '/reasoning/query', label: 'Impact query' }],
  },
  {
    title: 'Platform',
    items: [{ to: '/platform', label: 'Settings' }],
  },
]

function healthColor(
  status: string | undefined,
): 'green' | 'orange' | 'red' | 'grey' {
  if (status === 'ok') return 'green'
  if (status === 'degraded') return 'orange'
  if (status === 'error') return 'red'
  return 'grey'
}

function isNavActive(pathname: string, to: string, end?: boolean): boolean {
  return end ? pathname === to : pathname.startsWith(to)
}

export function AppLayout() {
  const location = useLocation()
  const health = useHealthPoll()

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadToggle>
          <PageToggleButton
            variant="plain"
            aria-label="Global navigation"
            id="nav-toggle"
          >
            <BarsIcon />
          </PageToggleButton>
        </MastheadToggle>
        <MastheadBrand>
          <MastheadLogo href="/" component="a">
            <Title headingLevel="h1" size="lg">
              General Simulation Admin
            </Title>
          </MastheadLogo>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar id="masthead-toolbar" isFullHeight>
          <ToolbarContent>
            <ToolbarItem align={{ default: 'alignEnd' }}>
              <Label color={healthColor(health?.status)}>
                API: {health?.status ?? 'checking…'}
                {health?.db ? ` · DB ${health.db}` : ''}
              </Label>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  )

  const pageNav = (
    <Nav aria-label="Admin console">
      <NavList>
        <NavItem
          itemId="/"
          isActive={location.pathname === '/'}
        >
          <NavLink to="/" end>Overview</NavLink>
        </NavItem>
      </NavList>
      {NAV_SECTIONS.map((section) => (
        <NavGroup key={section.title} title={section.title}>
          <NavList>
            {section.items.map((item) => (
              <NavItem
                key={item.to}
                itemId={item.to}
                isActive={isNavActive(location.pathname, item.to, item.end)}
              >
                <NavLink to={item.to} end={item.end}>
                  {item.label}
                </NavLink>
              </NavItem>
            ))}
          </NavList>
        </NavGroup>
      ))}
    </Nav>
  )

  const sidebar = (
    <PageSidebar>
      <PageSidebarBody>{pageNav}</PageSidebarBody>
    </PageSidebar>
  )

  return (
    <Page
      masthead={masthead}
      sidebar={sidebar}
      isManagedSidebar
      defaultManagedSidebarIsOpen
      skipToContent={
        <SkipToContent href="#main-content">Skip to content</SkipToContent>
      }
      mainContainerId="main-content"
    >
      <Outlet />
    </Page>
  )
}

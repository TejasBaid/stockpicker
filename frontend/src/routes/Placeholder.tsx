import { PageHeader } from '@/components/layout/AppShell'
import { Card, CardBody } from '@/components/ui/card'

/**
 * Phase 0 stand-in. Each of these is replaced by the real surface as its phase
 * lands: screener and research in phase 2, strategies and backtests in phase 3,
 * portfolio and alerts in phase 4.
 */
export function Placeholder({
  title,
  description,
  phase,
}: {
  title: string
  description: string
  phase: string
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <div className="p-6">
        <Card>
          <CardBody className="text-muted text-sm">
            Arriving in {phase}. The foundation — database, auth and app shell — is in place.
          </CardBody>
        </Card>
      </div>
    </>
  )
}

import { HarvestEntryForm } from "./HarvestEntryForm";

/** Harvest kiosk home (the 'field' role's only real page) — no PageLayout
 *  chrome here (KioskShell already supplies the page frame). No title block
 *  either: the tab bar right above already reads "Log harvest" for the
 *  active tab, and every line of vertical space here is one the kiosk's
 *  no-scroll shell (KioskShell) has to fit the form itself into. */
export function HarvestEntryPage() {
  return <HarvestEntryForm />;
}

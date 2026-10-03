/*
 * Methodology - one page that defines every number on the site, where it
 * comes from, and what it does NOT claim. Every section here was written
 * against the pipeline code, not from memory. If the pipeline changes,
 * change this page in the same commit.
 */
export default function Methodology({ onClose }) {
  return (
    <div className="method-overlay" role="dialog" aria-modal="true" aria-label="Methodology">
      <div className="method-panel">
        <button type="button" className="pill method-close" onClick={onClose}>Close ✕</button>
        <h2 className="method-title">How these numbers are made</h2>
        <p className="method-intro">
          Every figure on this site comes from an official public source, is
          fetched automatically on a nightly schedule, and is shown without
          interpretation. This page defines each one. If a number cannot be
          sourced, the site shows nothing rather than a guess.
        </p>

        <h3>Who is listed</h3>
        <p>
          The member roster comes from the public-domain congress-legislators
          dataset maintained by the unitedstates project, the same dataset used
          by major news organizations. It includes non-voting delegates and the
          Resident Commissioner, which is why the member count exceeds 535.
          Committee assignments come from the same project.
        </p>

        <h3>Bills</h3>
        <p>
          Sponsored bills come from the official Congress.gov API, maintained
          by the Library of Congress. Each member's most recent bills are
          shown; the count badge shows the true total on record. Topic tags are
          Congress.gov's own policy-area classification. Bill summaries are
          written by the Congressional Research Service (CRS), a nonpartisan
          agency of the Library of Congress, and are shown with attribution;
          bills too new to have a CRS summary show none, because this site does
          not write its own. Where a bill title references an executive order
          by number, the order's official title is fetched from the Federal
          Register, the government's system of record. Status labels such as
          "In committee" or "Became law" restate the bill's official latest
          action from Congress.gov; where the latest action is ambiguous, no
          label is shown. A member's sponsored total counts every measure on
          record at Congress.gov including amendments; the cards display bills
          and resolutions only, which is why the cards can number fewer than
          the total.
        </p>

        <h3>Voting records</h3>
        <p>
          House roll-call votes come from the Congress.gov House Roll Call
          Votes API, published in partnership with the Office of the Clerk.
          Senate roll-call votes come from the Senate's own public XML feeds at
          senate.gov. "Votes with party" is the share of party-split votes, those
          where the two parties' majorities went opposite ways, in which the
          member voted with their own party's majority. "Votes missed" is the
          share of roll calls where the member did not vote. Both are computed
          over the most recent roll calls noted on the member's card.
        </p>

        <h3>Campaign finance</h3>
        <p>
          All campaign finance figures come from the Federal Election
          Commission (FEC) API and reflect the candidate's principal campaign
          committee filings for the current election cycle. "PAC money" on this
          site means contributions from other political committees plus party
          committees, as reported on FEC committee totals. "Share of money from
          PACs" in the comparison table is PAC money divided by total receipts.
          "Members reporting $0 from PACs" counts members whose filings show
          exactly zero dollars in such contributions, computed from raw dollar
          amounts, never from rounded percentages. Percentages shown on member
          profiles, member cards and the table ("PAC share"), and elections
          cards are the share of contributions that came
          from PACs and party committees rather than individuals (small
          unitemized donations included), rounded to whole numbers; a share
          that rounds to zero shows as &ldquo;&lt;1%&rdquo; when any PAC money was
          received.
        </p>

        <h3>Stock trade disclosures</h3>
        <p>
          Trade disclosure counts come from Periodic Transaction Reports (PTRs)
          filed under the STOCK Act: House filings from the Clerk of the
          House's public financial-disclosure index, Senate filings from the
          Senate's electronic financial disclosure system where noted. A count
          of zero means no PTR is on file for this Congress, which can mean the
          member made no covered trades.
        </p>

        <h3>Elections preview</h3>
        <p>
          Candidate finance in the elections view comes from the FEC API using
          each campaign's verified committee IDs. Named donors are the largest
          itemized receipts from committee-type contributors on FEC Schedule A,
          restricted to contribution lines for party committees and other
          political committees so that transfers from a candidate's own
          joint-fundraising committees are not miscounted as donors. Each donor
          tag ("corporate PAC", "labor union PAC", "party committee") is the
          FEC's own classification of that committee; ActBlue and WinRed are
          labeled as conduits because the FEC registers them as pass-throughs
          for bundled individual donations. Outside spending is the FEC's tally
          of independent expenditures for and against each candidate across the
          whole election period, grouped by the committee that spent it; by law
          these groups may not coordinate with the campaigns. Candidate backgrounds and quick
          facts cite Ballotpedia; photos come from Wikimedia Commons with the
          license credited; campaign site links go to the candidates' own
          pages. Candidates whose committees have not yet filed show "n/a"
          rather than an estimate.
        </p>

        <h3>State legislatures</h3>
        <p>
          State data comes from LegiScan, a nonpartisan legislative data
          service, under its CC BY 4.0 license, via its official bulk
          datasets: a complete archive of every bill, roll call, and member
          for the current session, refreshed weekly when LegiScan's dataset
          hash changes. Each legislator's sponsored bills, "votes with party"
          and "votes missed" are computed from that archive using the same
          definitions as the federal view. Bill status labels translate
          LegiScan's official progress codes into plain terms: "Passed one
          chamber" is the formal status Engrossed, and "Sent to governor" is
          Enrolled (passed both chambers). Topic tags are LegiScan's own
          subject classifications. Bills whose status code is unrecognized
          show no label.
        </p>

        <h3>District lookup</h3>
        <p>
          The district finder sends the entered location directly from the
          visitor's browser to OpenStreetMap (to resolve text to a map point)
          and the United States Census Bureau geocoder (to resolve the point to
          current congressional and state legislative districts). This site
          never receives or stores the location. Results from a zip code or
          city are labeled approximate because those areas can span district
          lines.
        </p>

        <h3>Update schedule and corrections</h3>
        <p>
          Data refreshes run nightly via automated workflows. Each dataset
          carries its own last-updated stamp, shown in the page footer and on
          the elections view. A refresh that fails its quality checks publishes
          nothing, so the previous good data stays live; a stale stamp is the
          honest signal of that. Corrections are welcome: every figure links to
          its source so it can be checked by anyone.
        </p>
      </div>
    </div>
  );
}

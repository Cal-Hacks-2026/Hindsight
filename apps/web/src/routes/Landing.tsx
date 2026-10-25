// The first screen with no profile yet. No sign-up: the button goes straight to onboarding.
import { Link } from "react-router";
import { Icon } from "../components/Icons";
import { Masthead } from "../components/Paper";

export function Landing() {
  return (
    <div className="landing">
      <Masthead
        sketch="cap"
        byline="See what counts, what to take next and what could delay your transfer, from community college through graduation."
      >
        Plan Your Four-Year Journey.
      </Masthead>
      <Link to="/onboarding" className="button primary landing-start">
        Start With Your Path <Icon name="arrow" size={18} />
      </Link>
    </div>
  );
}

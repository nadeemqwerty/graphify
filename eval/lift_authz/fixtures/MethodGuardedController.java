package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.access.prepost.PreAuthorize;

/**
 * THE DIFFERENTIATOR. No class-level guard. secure() is method-guarded, but
 * open() is an unauthenticated endpoint. Fully guarded == false.
 *
 * A naive `grep PreAuthorize` on this file sees the annotation present and
 * wrongly concludes the whole controller is guarded (false positive).
 */
@RestController
public class MethodGuardedController {

    @GetMapping("/m/secure")
    @PreAuthorize("hasRole('ADMIN')")
    public String secure() {
        return "s";
    }

    @GetMapping("/m/open")
    public String open() {
        return "o";
    }
}

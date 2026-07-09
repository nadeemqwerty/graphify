package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.access.prepost.PreAuthorize;

/**
 * No class-level guard, but EVERY endpoint carries its own method-level
 * PreAuthorize annotation, so the controller is in fact fully guarded == true.
 *
 * This is the case where the naive grep baseline is right by luck: it only
 * checks presence of the token. The graph reaches the same answer by proving
 * every endpoint method has an authz_guard edge. Included so the eval does not
 * merely reward "predict the opposite of grep".
 */
@RestController
public class MixedController {

    @GetMapping("/x/one")
    @PreAuthorize("hasRole('ADMIN')")
    public String one() {
        return "1";
    }

    @GetMapping("/x/two")
    @PreAuthorize("hasRole('USER')")
    public String two() {
        return "2";
    }
}

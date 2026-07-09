package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.security.access.prepost.PreAuthorize;

/**
 * Class-level PreAuthorize annotation: authorization is enforced on EVERY
 * endpoint of this controller. Fully guarded == true.
 */
@RestController
@PreAuthorize("hasRole('ADMIN')")
public class ClassGuardedController {

    @GetMapping("/c/a")
    public String a() {
        return "a";
    }

    @GetMapping("/c/b")
    public String b() {
        return "b";
    }
}

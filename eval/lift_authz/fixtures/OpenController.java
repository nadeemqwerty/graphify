package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * No authorization anywhere. Fully guarded == false. Naive grep also gets this
 * right (no PreAuthorize annotation present), so it is a fair negative control.
 */
@RestController
public class OpenController {

    @GetMapping("/o/ping")
    public String ping() {
        return "pong";
    }
}
